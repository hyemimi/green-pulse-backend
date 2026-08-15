#!/usr/bin/env python3
"""
Standalone chemical-process early fault diagnosis pipeline.

This file contains the actual experiment logic in one Python file:
  1. F1/F3 thermal multi-CUSUM + regime-specific ML
  2. F2 bilateral-CUSUM / negative-bias / coolant verifier
  3. F4 vibration-centered verifier
  4. Specialist integration
  5. Thermal arbitration

No external ./scripts directory or intermediate CSV is required.\nThe ONLY input is the original chemical_process_timeseries CSV.\n\nExecution starts by calling pandas.read_csv() on that raw file, validating\ncolumns, sorting by reactor/time, interpolating sensor gaps, and creating\nepisodes + the chronological fit/cal/test split.\n\nInput file:
    chemical_process_timeseries.csv

Place the CSV in the same directory as this Python file.

Example:
    python fault_diagnosis_pipeline.py --workspace ./fault_run

The code preserves the experiment logic used during development while replacing
hard-coded /mnt/data paths with the selected workspace.
"""

from pathlib import Path
import argparse
import os
import shutil
import pandas as pd
import numpy as np

WORKSPACE = Path('.')
DATA_FILE = Path(__file__).resolve().parent / 'chemical_process_timeseries.csv'


def load_raw_csv(data_path: str | Path = DATA_FILE) -> pd.DataFrame:
    """Load and preprocess the ORIGINAL CSV.

    This is the only external data input required by the pipeline.
    All later specialist stages are generated from this dataframe.
    """
    path = Path(data_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Raw CSV not found: {path}")

    print(f"[DATA] loading raw CSV: {path}")
    df = pd.read_csv(path, parse_dates=['timestamp'])

    required = [
        'timestamp', 'reactor_id', 'fault_type',
        'reactor_temp', 'reactor_pressure', 'feed_flow_rate',
        'coolant_flow_rate', 'agitator_speed_rpm', 'vibration_rms',
        'motor_current', 'power_consumption_kw',
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # Causal order is essential for every rolling/CUSUM feature.
    df = df.sort_values(['reactor_id', 'timestamp']).reset_index(drop=True)
    df['regime'] = df['reactor_id'].astype(str).str[0]

    sensor_cols = [
        'reactor_temp', 'reactor_pressure', 'feed_flow_rate',
        'coolant_flow_rate', 'agitator_speed_rpm', 'vibration_rms',
        'motor_current', 'power_consumption_kw',
    ]
    df[sensor_cols] = (
        df.groupby('reactor_id')[sensor_cols]
          .transform(lambda x: x.interpolate(method='linear', limit_direction='both'))
    )

    # Fault episodes: a new episode starts whenever fault_type changes
    # inside a reactor (or when the reactor changes).
    new_episode = (
        df['fault_type'].ne(df.groupby('reactor_id')['fault_type'].shift())
        | df['reactor_id'].ne(df['reactor_id'].shift())
    )
    df['episode_id'] = new_episode.cumsum().astype(np.int32)

    # Chronological split used throughout the later experiments.
    # Per reactor: first 45% fit, next 15% calibration, last 40% test.
    split = np.empty(len(df), dtype=object)
    for rid, g in df.groupby('reactor_id', sort=False):
        n = len(g)
        a, b = int(0.45*n), int(0.60*n)
        arr = np.full(n, 'test', dtype=object)
        arr[:a] = 'fit'
        arr[a:b] = 'cal'
        split[g.index] = arr
    df['split_name'] = split
    df['split'] = pd.Series(split).map({'fit': 0, 'cal': 1, 'test': 2}).astype(np.int8)

    print(f"[DATA] rows={len(df):,}, columns={len(df.columns)}")
    print(f"[DATA] reactors={df['reactor_id'].nunique()}, episodes={df['episode_id'].nunique()}")
    print('[DATA] fault counts:')
    print(df['fault_type'].value_counts().sort_index().to_string())
    print(f"[DATA] remaining sensor NaN={int(df[sensor_cols].isna().sum().sum())}")
    return df


def prepare_workspace_from_raw(df: pd.DataFrame, workspace: str) -> None:
    """Persist the preprocessed dataframe for the embedded specialist stages.

    The specialist code below was developed as separate experiments, so each stage
    re-reads a canonical CSV.  These files are generated here from the single raw
    dataframe above; they are NOT additional user inputs.
    """
    global WORKSPACE
    WORKSPACE = Path(workspace).resolve()
    WORKSPACE.mkdir(parents=True, exist_ok=True)

    # Remove helper-only columns before saving the canonical dataset so all stages
    # see the same original schema plus any original extra columns.
    save_df = df.drop(columns=['split_name', 'split', 'episode_id', 'regime'], errors='ignore')
    canonical = WORKSPACE / 'chemical_process_timeseries.csv'
    save_df.to_csv(canonical, index=False)

    # Small human-readable summaries for GitHub / experiment tracking.
    summary = (
        df.groupby(['reactor_id', 'split_name', 'fault_type'])
          .size().rename('rows').reset_index()
    )
    summary.to_csv(WORKSPACE / 'dataset_split_fault_summary.csv', index=False)

    episode_summary = (
        df.groupby('episode_id', as_index=False)
          .agg(
              reactor_id=('reactor_id', 'first'),
              fault_type=('fault_type', 'first'),
              split_name=('split_name', 'first'),
              onset=('timestamp', 'min'),
              end=('timestamp', 'max'),
              rows=('timestamp', 'size'),
          )
    )
    episode_summary.to_csv(WORKSPACE / 'episode_summary.csv', index=False)



def _prepare_integration_inputs():
    src = WORKSPACE / 'f2_stage3_3feature_verifier' / 'all_stage2_events_with_stage3_scores.csv'
    dst_dir = WORKSPACE / 'integration_work' / 'f2_stage3_3feature_verifier'
    dst_dir.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        raise FileNotFoundError(f'F2 integration input missing: {src}')
    shutil.copy2(src, dst_dir / src.name)



# ==============================================================================
# 01_thermal_multicusum_normalml
# ==============================================================================
def run_thermal_f1_f3():
    import os, warnings, zipfile, math
    warnings.filterwarnings('ignore')
    import numpy as np
    import pandas as pd
    from numba import njit
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.ensemble import IsolationForest
    from sklearn.decomposition import PCA
    from sklearn.metrics import roc_auc_score
    import xgboost as xgb
    import matplotlib.pyplot as plt

    DATA=str(WORKSPACE) + '/chemical_process_timeseries.csv'
    OUT=str(WORKSPACE) + '/thermal_multicusum_normalml_outputs'
    os.makedirs(OUT,exist_ok=True)
    IDS=['A_R1','A_R2','A_R3','B_R1','B_R2','B_R3']
    S=['reactor_temp','reactor_pressure','feed_flow_rate','coolant_flow_rate','agitator_speed_rpm','vibration_rms','motor_current','power_consumption_kw']
    RNG=np.random.RandomState(42)
    REFRACTORY=3
    print('load...',flush=True)
    df=pd.read_csv(DATA,usecols=['timestamp','reactor_id','fault_type']+S)
    df['timestamp']=pd.to_datetime(df['timestamp'])
    df=df.sort_values(['reactor_id','timestamp']).reset_index(drop=True)
    idcode=pd.Categorical(df.reactor_id,categories=IDS).codes.astype(np.int8)
    fault=df.fault_type.to_numpy(np.int8)
    N=len(df); block=N//6
    pos=np.tile(np.arange(block),6)
    FIT=int(block*.45); CAL=int(block*.60)
    split=np.where(pos<FIT,0,np.where(pos<CAL,1,2)).astype(np.int8)
    reg=(idcode>=3).astype(np.int8)

    # interpolate
    A={}
    for c in S:
        x=df[c].to_numpy(float)
        for k in range(6):
            sl=slice(k*block,(k+1)*block); y=x[sl].copy(); good=np.isfinite(y)
            if not good.all():
                y[~good]=np.interp(np.flatnonzero(~good),np.flatnonzero(good),y[good]); x[sl]=y
        A[c]=x

    # episode ids
    EP=np.empty(N,np.int32); EPM=np.empty(N,np.int32); segments=[]; eid=0
    for k in range(6):
        st=k*block; f=fault[st:st+block]
        ch=np.r_[0,np.flatnonzero(f[1:]!=f[:-1])+1,block]
        for a,b in zip(ch[:-1],ch[1:]):
            EP[st+a:st+b]=eid; EPM[st+a:st+b]=np.arange(b-a)
            segments.append((eid,k,int(f[a]),st+a,st+b)); eid+=1

    # helpers
    def rolling_mean_block(x,w):
        out=np.empty_like(x,dtype=np.float64)
        for k in range(6):
            st=k*block; y=x[st:st+block]
            cs=np.r_[0.,np.cumsum(y,dtype=np.float64)]
            ii=np.arange(block); lo=np.maximum(0,ii-w+1)
            out[st:st+block]=(cs[ii+1]-cs[lo])/(ii-lo+1)
        return out

    def shift_block(x,w):
        out=np.full(len(x),np.nan,dtype=np.float64)
        for k in range(6):
            st=k*block; out[st+w:st+block]=x[st:st+block-w]
        return out

    # reactor-normalized raw sensors (fit-normal only)
    Z=np.empty((N,len(S)),np.float32); norm_rows=[]
    for j,c in enumerate(S):
        x=A[c]
        for k,rid in enumerate(IDS):
            sl=slice(k*block,(k+1)*block); m=(split[sl]==0)&(fault[sl]==0)
            mu=float(x[sl][m].mean()); sd=float(x[sl][m].std()); sd=max(sd,1e-9)
            Z[sl,j]=((x[sl]-mu)/sd).astype(np.float32)
            if j==0: norm_rows.append({'reactor_id':rid,'regime':rid[0]})
            norm_rows[-1][c+'_mu']=mu; norm_rows[-1][c+'_sd']=sd
    pd.DataFrame(norm_rows).to_csv(f'{OUT}/reactor_normal_stats.csv',index=False)

    # causal short-vs-past residuals for thermal CUSUM
    jT=S.index('reactor_temp'); jP=S.index('reactor_pressure'); jC=S.index('coolant_flow_rate')
    zT=Z[:,jT].astype(float); zP=Z[:,jP].astype(float); zC=Z[:,jC].astype(float)
    curT=rolling_mean_block(zT,3); curP=rolling_mean_block(zP,3); curC=rolling_mean_block(zC,3)
    pastT=shift_block(rolling_mean_block(zT,30),1)
    pastP=shift_block(rolling_mean_block(zP,30),1)
    pastC=shift_block(rolling_mean_block(zC,30),1)
    # directional raw residuals: + = expected thermal fault direction
    rC_raw=pastC-curC       # coolant drop
    rT_raw=curT-pastT       # temp rise
    rP_raw=curP-pastP       # signed pressure change
    valid=np.isfinite(rC_raw)&np.isfinite(rT_raw)&np.isfinite(rP_raw)
    # standardize residuals by each reactor fit-normal residual distribution
    RC=np.full(N,np.nan,np.float32); RT=np.full(N,np.nan,np.float32); RP=np.full(N,np.nan,np.float32)
    res_rows=[]
    for k,rid in enumerate(IDS):
        sl=slice(k*block,(k+1)*block); m=(split[sl]==0)&(fault[sl]==0)&valid[sl]
        for arr,name,out in [(rC_raw,'coolant_drop',RC),(rT_raw,'temp_rise',RT),(rP_raw,'pressure_change',RP)]:
            mu=float(np.mean(arr[sl][m])); sd=float(np.std(arr[sl][m])); sd=max(sd,1e-6)
            out[sl]=((arr[sl]-mu)/sd).astype(np.float32)
            res_rows.append({'reactor_id':rid,'signal':name,'mu':mu,'sd':sd})
    pd.DataFrame(res_rows).to_csv(f'{OUT}/cusum_residual_stats.csv',index=False)

    @njit
    def cusum_events_block(rc,rt,rp,kdrift,h,refractory):
        n=len(rc); ev=np.zeros(n,np.uint8)
        cpre=np.zeros(n,np.float32); tpre=np.zeros(n,np.float32); pupre=np.zeros(n,np.float32); pdnre=np.zeros(n,np.float32)
        c=t=pu=pdn=0.0; last=-100000
        for i in range(n):
            a=rc[i]; b=rt[i]; p=rp[i]
            if np.isnan(a) or np.isnan(b) or np.isnan(p):
                c=t=pu=pdn=0.0; continue
            c=max(0.0,c+(a-kdrift))
            t=max(0.0,t+(b-kdrift))
            pu=max(0.0,pu+(p-kdrift))
            pdn=max(0.0,pdn+((-p)-kdrift))
            cpre[i]=c; tpre[i]=t; pupre[i]=pu; pdnre[i]=pdn
            thermal=math.sqrt(c*c+t*t)
            if thermal>=h and i-last>=refractory:
                ev[i]=1; last=i
                # reset after real emitted alarm so alarm rate is honest
                c=t=pu=pdn=0.0
        return ev,cpre,tpre,pupre,pdnre

    def generate_events(kdrift,h,rc_filter=None):
        idxs=[]; feats=[]
        for kk in range(6):
            if rc_filter is not None and (1 if kk>=3 else 0)!=rc_filter: continue
            st=kk*block; en=st+block
            ev,c,t,pu,pd_=cusum_events_block(RC[st:en],RT[st:en],RP[st:en],kdrift,h,REFRACTORY)
            loc=np.flatnonzero(ev)
            if len(loc):
                gi=st+loc
                # compact CUSUM + instantaneous residual features
                C=c[loc].astype(float); T=t[loc].astype(float); PU=pu[loc].astype(float); PD=pd_[loc].astype(float)
                F=np.column_stack([
                    np.log1p(C),np.log1p(T),np.log1p(PU),np.log1p(PD),
                    C/(C+T+1e-6), T/(C+T+1e-6), np.log1p(C+T),
                    RC[gi],RT[gi],RP[gi]
                ]).astype(np.float32)
                idxs.append(gi); feats.append(F)
        if not idxs: return np.array([],int),np.empty((0,10),np.float32)
        return np.concatenate(idxs),np.vstack(feats)

    feat_names=['log_Ccool','log_Ctemp','log_Pup','log_Pdown','cool_share','temp_share','log_thermal_sum','resid_cool','resid_temp','resid_pressure']

    def episode_metrics_from_events(evdf, split_codes, rn=None, pred_col='pred'):
        if isinstance(split_codes,int): split_codes=[split_codes]
        rows=[]
        for e,k,ft,a,b in segments:
            if ft not in (1,3) or split[a] not in split_codes: continue
            rr='B' if k>=3 else 'A'
            if rn is not None and rr!=rn: continue
            g=evdf[(evdf.idx>=a)&(evdf.idx<b)].sort_values('idx')
            if len(g)==0:
                rows.append({'episode_id':e,'reactor_id':IDS[k],'regime':rr,'fault':ft,'correct_delay':np.nan,'wrong_delay':np.nan,'first_delay':np.nan,'first_pred':np.nan,'first_correct':False,'wrong_before_correct':False})
                continue
            gi=g.idx.to_numpy(int); pr=g[pred_col].to_numpy(int)
            cm=np.flatnonzero(pr==ft); wm=np.flatnonzero(pr!=ft)
            cd=float(gi[cm[0]]-a) if len(cm) else np.nan
            wd=float(gi[wm[0]]-a) if len(wm) else np.nan
            rows.append({'episode_id':e,'reactor_id':IDS[k],'regime':rr,'fault':ft,'correct_delay':cd,'wrong_delay':wd,'first_delay':float(gi[0]-a),'first_pred':int(pr[0]),'first_correct':bool(pr[0]==ft),'wrong_before_correct':bool(np.isfinite(wd) and (not np.isfinite(cd) or wd<cd))})
        return pd.DataFrame(rows)

    def make_logit():
        return LogisticRegression(C=.4,class_weight='balanced',max_iter=2000,random_state=42)

    def make_xgb():
        return xgb.XGBClassifier(n_estimators=80,max_depth=2,learning_rate=.05,subsample=.85,colsample_bytree=.9,min_child_weight=2,reg_lambda=3,reg_alpha=.3,objective='binary:logistic',eval_metric='logloss',random_state=42,n_jobs=2)

    # Stage 1 grid: select k/h and classifier by episode-OOF on train+cal fault episodes.
    # Normal cal rate is only a mild penalty because stage 2 is expected to filter candidates.
    configs=[]; grid_rows=[]
    Ks=[.10,.20,.30,.45,.60]
    Hs=[1.5,2.0,2.5,3.0,4.0,5.0,6.0]
    for rc,rn in [(0,'A'),(1,'B')]:
        best=None
        for kd in Ks:
            for h in Hs:
                idx,F=generate_events(kd,h,rc)
                if len(idx)==0: continue
                ed=pd.DataFrame({'idx':idx})
                ed['episode_id']=EP[idx]; ed['fault']=fault[idx]; ed['split']=split[idx]; ed['ep_min']=EPM[idx]
                early=(ed['split']<2)&ed.fault.isin([1,3])&(ed.ep_min<=30)
                trrows=np.flatnonzero(early.to_numpy())
                if len(trrows)<8: continue
                eps=np.unique(ed.episode_id.to_numpy()[trrows])
                # ensure both classes exist overall
                yy=(fault[idx[trrows]]==3).astype(int)
                if len(np.unique(yy))<2: continue
                for model_name in ['logit','xgb']:
                    poof=np.full(len(ed),np.nan,float)
                    # Leave one fault episode out; train only other early fault candidate events
                    for e in eps:
                        va=np.flatnonzero(early.to_numpy()&(ed.episode_id.to_numpy()==e))
                        tr=np.flatnonzero(early.to_numpy()&(ed.episode_id.to_numpy()!=e))
                        if len(va)==0 or len(tr)<4: continue
                        y=(fault[idx[tr]]==3).astype(int)
                        if len(np.unique(y))<2: continue
                        sc=StandardScaler().fit(F[tr])
                        m=make_logit() if model_name=='logit' else make_xgb()
                        m.fit(sc.transform(F[tr]),y)
                        poof[va]=m.predict_proba(sc.transform(F[va]))[:,1]
                    use=np.isfinite(poof)
                    if use.sum()==0: continue
                    e2=ed.loc[use,['idx','episode_id','fault','split','ep_min']].copy()
                    e2['pred']=np.where(poof[use]>=.5,3,1)
                    met=episode_metrics_from_events(e2,[0,1],rn)
                    # because OOF can lack events in some episode if the held-out prediction unavailable, reindex expected eps
                    w5=float((met.correct_delay<=5).fillna(False).mean()) if len(met) else 0
                    w15=float((met.correct_delay<=15).fillna(False).mean()) if len(met) else 0
                    w30=float((met.correct_delay<=30).fillna(False).mean()) if len(met) else 0
                    first=float(met.first_correct.mean()) if len(met) else 0
                    wrong=float(met.wrong_before_correct.mean()) if len(met) else 1
                    det=float(met.correct_delay.notna().mean()) if len(met) else 0
                    med=float(met.correct_delay.median()) if met.correct_delay.notna().any() else 9999
                    calnorm=(split[idx]==1)&(fault[idx]==0)
                    days=((reg==rc)&(split==1)&(fault==0)).sum()/1440.
                    fa=float(calnorm.sum()/max(days,1e-9))
                    score=18*first+12*w5+10*w15+8*w30+2*det-12*wrong-0.015*fa-0.01*med
                    rec={'regime':rn,'k':kd,'h':h,'classifier':model_name,'oof_first_correct':first,'oof_w5':w5,'oof_w15':w15,'oof_w30':w30,'oof_detect':det,'oof_wrong_before':wrong,'oof_median_delay':med,'cal_candidate_events_day':fa,'objective':score,'n_early_candidate_rows':len(trrows)}
                    grid_rows.append(rec)
                    # prioritize first correctness, then 15/30, then wrong rate and speed
                    key=(first,w15,w30,-wrong,-med,score)
                    if best is None or key>best[0]: best=(key,rec,idx,F)
        if best is None: raise RuntimeError('no config '+rn)
        configs.append(best[1]); print('stage1 selected',best[1],flush=True)

    pd.DataFrame(grid_rows).to_csv(f'{OUT}/stage1_cusum_grid.csv',index=False)
    pd.DataFrame(configs).to_csv(f'{OUT}/stage1_selected.csv',index=False)

    # Fit chosen stage1 classifier on all train+cal early candidate events, predict all candidate events
    all_events=[]; stage1_models={}; stage1_scalers={}
    for cfg in configs:
        rn=cfg['regime']; rc=0 if rn=='A' else 1
        idx,F=generate_events(cfg['k'],cfg['h'],rc)
        early=(split[idx]<2)&np.isin(fault[idx],[1,3])&(EPM[idx]<=30)
        y=(fault[idx[early]]==3).astype(int)
        sc=StandardScaler().fit(F[early])
        m=make_logit() if cfg['classifier']=='logit' else make_xgb()
        m.fit(sc.transform(F[early]),y)
        p3=m.predict_proba(sc.transform(F))[:,1]
        pred=np.where(p3>=.5,3,1).astype(np.int8)
        ed=pd.DataFrame({'idx':idx,'reactor_id':[IDS[x//block] for x in idx],'regime':rn,'split':split[idx],'episode_id':EP[idx],'ep_min':EPM[idx],'true_fault':fault[idx],'pred':pred,'p_F3':p3})
        for j,nm in enumerate(feat_names): ed[nm]=F[:,j]
        all_events.append(ed); stage1_models[rn]=m; stage1_scalers[rn]=sc
    EV=pd.concat(all_events,ignore_index=True).sort_values('idx').reset_index(drop=True)

    # Stage 2 normal-only feature construction: all 8 current z + 1/3/5/10 min diffs + rolling std5 + CUSUM event descriptors.
    # Model is trained from ALL fit-normal rows (sampled), not trigger-filtered rows.
    basefeat=[Z]
    base_names=[f'{s}_z' for s in S]
    for w in [1,3,5,10]:
        D=np.full_like(Z,np.nan,np.float32)
        for k in range(6):
            st=k*block; D[st+w:st+block]=Z[st+w:st+block]-Z[st:st+block-w]
        basefeat.append(D); base_names += [f'{s}_d{w}' for s in S]
    # 5m rolling std
    RS=np.empty_like(Z,np.float32)
    for j in range(len(S)):
        x=Z[:,j].astype(float); rm=rolling_mean_block(x,5); rm2=rolling_mean_block(x*x,5); RS[:,j]=np.sqrt(np.maximum(0,rm2-rm*rm)).astype(np.float32)
    basefeat.append(RS); base_names += [f'{s}_std5' for s in S]
    BF=np.column_stack(basefeat).astype(np.float32)
    valid_bf=np.isfinite(BF).all(1)

    # normal-only models per regime
    normal_models={}; normal_scalers={}; pca_models={}; normal_score_rows=[]
    for rc,rn in [(0,'A'),(1,'B')]:
        m=(reg==rc)&(split==0)&(fault==0)&valid_bf
        inds=np.flatnonzero(m)
        # broad sample across the full fit-normal period
        if len(inds)>50000: inds=np.sort(RNG.choice(inds,50000,replace=False))
        sc=StandardScaler().fit(BF[inds])
        Xn=sc.transform(BF[inds])
        iso=IsolationForest(n_estimators=180,max_samples=min(4096,len(inds)),contamination='auto',random_state=42,n_jobs=2).fit(Xn)
        pca=PCA(n_components=.95,svd_solver='full',random_state=42).fit(Xn)
        normal_models[rn]=iso; normal_scalers[rn]=sc; pca_models[rn]=pca
        print('normal-only',rn,'train rows',len(inds),'pca comps',pca.n_components_,flush=True)

    # score candidate events with all-normal models
    EV['iso_anom']=np.nan; EV['pca_err']=np.nan
    for rn in ['A','B']:
        rows=np.flatnonzero(EV.regime.to_numpy()==rn); inds=EV.idx.to_numpy(int)[rows]
        ok=valid_bf[inds]
        if not np.any(ok): continue
        rr=rows[ok]; ii=inds[ok]
        X=normal_scalers[rn].transform(BF[ii])
        # higher = more anomalous
        EV.loc[rr,'iso_anom']=-normal_models[rn].score_samples(X)
        XP=pca_models[rn].transform(X); XR=pca_models[rn].inverse_transform(XP)
        EV.loc[rr,'pca_err']=np.mean((X-XR)**2,axis=1)

    # Calibrate stage2 thresholds on calibration normal candidates only; choose strict <=0.5/day and loose <=2/day
    filter_grid=[]; selected_filters=[]
    for rn in ['A','B']:
        rc=0 if rn=='A' else 1
        days=((reg==rc)&(split==1)&(fault==0)).sum()/1440.
        for scorecol in ['iso_anom','pca_err']:
            cal=EV[(EV.regime==rn)&(EV.split==1)&(EV.true_fault==0)&EV[scorecol].notna()]
            vals=cal[scorecol].to_numpy(float)
            if len(vals)==0: continue
            for q in [.90,.925,.95,.97,.98,.985,.99,.9925,.995,.9975,.999,.9995]:
                thr=float(np.quantile(vals,q))
                fa=float((vals>=thr).sum()/max(days,1e-9))
                # retention on train+cal thermal episodes, use final stage1 predictions but threshold selection not test
                tr=EV[(EV.regime==rn)&(EV.split<2)&EV.true_fault.isin([1,3])&EV[scorecol].notna()&(EV[scorecol]>=thr)].copy()
                met=episode_metrics_from_events(tr,[0,1],rn)
                w5=float((met.correct_delay<=5).fillna(False).mean()) if len(met) else 0
                w15=float((met.correct_delay<=15).fillna(False).mean()) if len(met) else 0
                w30=float((met.correct_delay<=30).fillna(False).mean()) if len(met) else 0
                first=float(met.first_correct.mean()) if len(met) else 0
                wrong=float(met.wrong_before_correct.mean()) if len(met) else 1
                det=float(met.correct_delay.notna().mean()) if len(met) else 0
                med=float(met.correct_delay.median()) if met.correct_delay.notna().any() else 9999
                filter_grid.append({'regime':rn,'model':scorecol,'q':q,'threshold':thr,'cal_fa_day':fa,'train_first_correct':first,'train_w5':w5,'train_w15':w15,'train_w30':w30,'train_detect':det,'train_wrong_before':wrong,'train_median_delay':med})
        gg=pd.DataFrame([x for x in filter_grid if x['regime']==rn])
        for opname,cap in [('strict_0.5',.5),('loose_2.0',2.0)]:
            cand=gg[gg.cal_fa_day<=cap].copy()
            if len(cand)==0: cand=gg.nsmallest(1,'cal_fa_day')
            cand['sel_score']=15*cand.train_w15+10*cand.train_w30+8*cand.train_first_correct+2*cand.train_detect-8*cand.train_wrong_before-.01*cand.train_median_delay
            sel=cand.sort_values(['sel_score','cal_fa_day'],ascending=[False,True]).iloc[0]
            rec=sel.drop(labels=['sel_score']).to_dict(); rec['operating_point']=opname; selected_filters.append(rec)
    pd.DataFrame(filter_grid).to_csv(f'{OUT}/normal_filter_grid.csv',index=False)
    pd.DataFrame(selected_filters).to_csv(f'{OUT}/normal_filter_selected.csv',index=False)

    # Evaluation functions
    def summarize(stage, ev):
        met=episode_metrics_from_events(ev,2)
        testnorm=(split==2)&(fault==0); days=testnorm.sum()/1440.
        normal_events=ev[(ev.split==2)&(ev.true_fault==0)]
        fa=len(normal_events)/max(days,1e-9)
        rec={'stage':stage,'n_test_eps':len(met),'detected_rate':float(met.correct_delay.notna().mean()),'within5_rate':float((met.correct_delay<=5).fillna(False).mean()),'within15_rate':float((met.correct_delay<=15).fillna(False).mean()),'within30_rate':float((met.correct_delay<=30).fillna(False).mean()),'first_correct_rate':float(met.first_correct.mean()),'wrong_before_correct_rate':float(met.wrong_before_correct.mean()),'median_correct_delay':float(met.correct_delay.median()) if met.correct_delay.notna().any() else np.nan,'test_false_alarm_events_day':fa,'test_false_alarm_events':len(normal_events),'test_normal_reactor_days':days}
        met.insert(0,'stage',stage)
        return rec,met

    summ=[]; epouts=[]
    r,m=summarize('stage1_multicusum',EV); summ.append(r); epouts.append(m)
    for op in ['strict_0.5','loose_2.0']:
        pieces=[]
        for rn in ['A','B']:
            cfg=[x for x in selected_filters if x['regime']==rn and x['operating_point']==op][0]
            g=EV[(EV.regime==rn)&EV[cfg['model']].notna()&(EV[cfg['model']]>=cfg['threshold'])].copy(); pieces.append(g)
        e2=pd.concat(pieces,ignore_index=True)
        r,m=summarize('normalML_'+op,e2); summ.append(r); epouts.append(m)

    SUM=pd.DataFrame(summ); EPS=pd.concat(epouts,ignore_index=True)
    SUM.to_csv(f'{OUT}/overall_summary.csv',index=False); EPS.to_csv(f'{OUT}/test_episode_results.csv',index=False)
    EV.to_csv(f'{OUT}/all_candidate_events.csv',index=False)
    EV[EV.split==2].to_csv(f'{OUT}/test_candidate_events.csv',index=False)

    # Per-regime summary
    grows=[]
    for stage,ev in [('stage1_multicusum',EV)]:
        for rn in ['A','B']:
            met=episode_metrics_from_events(ev[ev.regime==rn],2,rn)
            rc=0 if rn=='A' else 1; days=((reg==rc)&(split==2)&(fault==0)).sum()/1440.; ne=len(ev[(ev.regime==rn)&(ev.split==2)&(ev.true_fault==0)])
            grows.append({'stage':stage,'regime':rn,'n_eps':len(met),'within15':(met.correct_delay<=15).fillna(False).mean(),'within30':(met.correct_delay<=30).fillna(False).mean(),'first_correct':met.first_correct.mean(),'wrong_before':met.wrong_before_correct.mean(),'median_delay':met.correct_delay.median(),'fa_day':ne/max(days,1e-9)})
    for op in ['strict_0.5','loose_2.0']:
        for rn in ['A','B']:
            cfg=[x for x in selected_filters if x['regime']==rn and x['operating_point']==op][0]
            ev=EV[(EV.regime==rn)&EV[cfg['model']].notna()&(EV[cfg['model']]>=cfg['threshold'])].copy()
            met=episode_metrics_from_events(ev,2,rn); rc=0 if rn=='A' else 1; days=((reg==rc)&(split==2)&(fault==0)).sum()/1440.; ne=len(ev[(ev.split==2)&(ev.true_fault==0)])
            grows.append({'stage':'normalML_'+op,'regime':rn,'n_eps':len(met),'within15':(met.correct_delay<=15).fillna(False).mean(),'within30':(met.correct_delay<=30).fillna(False).mean(),'first_correct':met.first_correct.mean(),'wrong_before':met.wrong_before_correct.mean(),'median_delay':met.correct_delay.median(),'fa_day':ne/max(days,1e-9)})
    pd.DataFrame(grows).to_csv(f'{OUT}/per_regime_summary.csv',index=False)

    # CUSUM charts for held-out thermal episodes: recompute selected regime CUSUM states without resets? Plot reset-state scores actually used.
    for e,k,ft,a,b in segments:
        if ft not in (1,3) or split[a]!=2: continue
        rn='B' if k>=3 else 'A'; cfg=[x for x in configs if x['regime']==rn][0]
        st=k*block; loc_a=a-st; loc_b=min(b-st,loc_a+90)
        ev,c,t,pu,pd_=cusum_events_block(RC[st:st+block],RT[st:st+block],RP[st:st+block],cfg['k'],cfg['h'],REFRACTORY)
        xx=np.arange(loc_b-loc_a)
        plt.figure(figsize=(10,5))
        plt.plot(xx,c[loc_a:loc_b],label='Coolant drop CUSUM')
        plt.plot(xx,t[loc_a:loc_b],label='Temperature rise CUSUM')
        plt.plot(xx,np.sqrt(c[loc_a:loc_b]**2+t[loc_a:loc_b]**2),label='Thermal combined')
        plt.axhline(cfg['h'],linestyle='--',label='Trigger h')
        plt.xlabel('Minutes after fault onset'); plt.ylabel('CUSUM score'); plt.title(f'{IDS[k]} F{ft} - {rn} multivariate CUSUM')
        plt.legend(); plt.tight_layout(); plt.savefig(f'{OUT}/cusum_episode_{e}_{IDS[k]}_F{ft}.png',dpi=150); plt.close()

    # compact comparison to previous trajectory if available
    comp=SUM.copy()
    prev=str(WORKSPACE) + '/thermal_f1f3_trajectory_sequence_outputs/overall_comparison.csv'
    if os.path.exists(prev):
        P=pd.read_csv(prev)
        P['source']='previous_trajectory'; comp['source']='multicusum'; pd.concat([P,comp],ignore_index=True,sort=False).to_csv(f'{OUT}/comparison_with_previous.csv',index=False)

    print('\nSELECTED STAGE1')
    print(pd.DataFrame(configs).to_string(index=False))
    print('\nSELECTED NORMAL FILTERS')
    print(pd.DataFrame(selected_filters).to_string(index=False))
    print('\nSUMMARY')
    print(SUM.to_string(index=False))
    print('\nTEST EPISODES')
    print(EPS.to_string(index=False))

    pkg=str(WORKSPACE) + '/thermal_multicusum_normalml_package.zip'
    with zipfile.ZipFile(pkg,'w',zipfile.ZIP_DEFLATED) as z:
        z.write(__file__,arcname=os.path.basename(__file__))
        for fn in os.listdir(OUT): z.write(os.path.join(OUT,fn),arcname='outputs/'+fn)
    print('package',pkg)


# ==============================================================================
# 02_f2_stage3_3feature_verifier
# ==============================================================================
def run_f2_specialist():
    import os, warnings
    warnings.filterwarnings('ignore')
    import numpy as np
    import pandas as pd
    from numba import njit
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score
    try:
        from xgboost import XGBClassifier
        HAVE_XGB = True
    except Exception:
        HAVE_XGB = False

    DATA = str(WORKSPACE) + '/chemical_process_timeseries.csv'
    OUT = str(WORKSPACE) + '/f2_stage3_3feature_verifier'
    os.makedirs(OUT, exist_ok=True)

    # ------------------------------------------------------------
    # Load + same chronological split
    # ------------------------------------------------------------
    cols = ['timestamp','reactor_id','feed_flow_rate','reactor_temp','coolant_flow_rate','fault_type']
    df = pd.read_csv(DATA, usecols=cols, parse_dates=['timestamp'])
    df = df.sort_values(['reactor_id','timestamp']).reset_index(drop=True)
    for c in ['feed_flow_rate','reactor_temp','coolant_flow_rate']:
        df[c] = df.groupby('reactor_id')[c].transform(lambda s: s.interpolate(limit_direction='both'))

    split = np.empty(len(df), dtype=object)
    for rid,g in df.groupby('reactor_id', sort=False):
        n=len(g); a=int(.45*n); b=int(.60*n)
        arr=np.full(n,'test',dtype=object); arr[:a]='fit'; arr[a:b]='cal'
        split[g.index]=arr
    df['split']=split
    new_ep=(df['fault_type'].ne(df.groupby('reactor_id')['fault_type'].shift()) |
            df['reactor_id'].ne(df['reactor_id'].shift()))
    df['episode_id']=new_ep.cumsum().astype(np.int32)

    N=len(df)
    reactors=list(df['reactor_id'].drop_duplicates())
    rcode=np.full(N,-1,np.int16)
    resid_z=np.full(N,np.nan)
    osc=np.zeros(N,dtype=bool)

    # ------------------------------------------------------------
    # Causal feature engineering
    # ------------------------------------------------------------
    df['feed_level_z']=np.nan
    df['feed_mean_z20']=np.nan
    df['feed_neg_frac20']=np.nan
    df['feed_neg_area20']=np.nan
    df['temp_slope20']=np.nan
    df['coolant_slope20']=np.nan
    df['temp_slope20_z']=np.nan
    df['coolant_slope20_z']=np.nan

    def rolling_slope(s, w=20):
        # Fast exact linear slope on sliding windows x=0..w-1
        arr=s.to_numpy(dtype=float)
        out=np.full(len(arr),np.nan)
        if len(arr)<w:
            return out
        x=np.arange(w,dtype=float)
        sumx=x.sum(); denom=((x-x.mean())**2).sum()
        valid=np.isfinite(arr).astype(float)
        arr0=np.nan_to_num(arr,nan=0.0)
        sumy=np.convolve(arr0,np.ones(w),mode='valid')
        dotxy=np.correlate(arr0,x,mode='valid')
        count=np.convolve(valid,np.ones(w),mode='valid')
        vals=(dotxy - sumx*sumy/w)/denom
        vals[count<w]=np.nan
        out[w-1:]=vals
        return out


    for rc,rid in enumerate(reactors):
        idx=df.index[df['reactor_id'].eq(rid)]
        g=df.loc[idx]
        x=g['feed_flow_rate'].astype(float)
        mean30=x.shift(1).rolling(30,min_periods=30).mean()
        sd30=x.shift(1).rolling(30,min_periods=30).std(ddof=0).replace(0,np.nan)
        fz=(x-mean30)/sd30
        df.loc[idx,'feed_level_z']=fz.to_numpy()
        df.loc[idx,'feed_mean_z20']=fz.rolling(20,min_periods=20).mean().to_numpy()
        df.loc[idx,'feed_neg_frac20']=(fz<0).astype(float).rolling(20,min_periods=20).mean().to_numpy()
        df.loc[idx,'feed_neg_area20']=(-fz.clip(upper=0)).rolling(20,min_periods=20).mean().to_numpy()

        ts=rolling_slope(g['reactor_temp'],20)
        cs=rolling_slope(g['coolant_flow_rate'],20)
        df.loc[idx,'temp_slope20']=ts
        df.loc[idx,'coolant_slope20']=cs

        fm=(g['split'].eq('fit') & g['fault_type'].eq(0)).to_numpy()
        tmu=np.nanmean(ts[fm]); tsd=np.nanstd(ts[fm]);
        cmu=np.nanmean(cs[fm]); csd=np.nanstd(cs[fm]);
        if not np.isfinite(tsd) or tsd<1e-12: tsd=1.0
        if not np.isfinite(csd) or csd<1e-12: csd=1.0
        df.loc[idx,'temp_slope20_z']=(ts-tmu)/tsd
        df.loc[idx,'coolant_slope20_z']=(cs-cmu)/csd

        # Stage1 feed residual CUSUM input
        cur3=x.rolling(3,min_periods=3).mean()
        past30=x.shift(1).rolling(30,min_periods=30).mean()
        r=cur3-past30
        fm2=g['split'].eq('fit') & g['fault_type'].eq(0) & r.notna()
        mu=r[fm2].mean(); sd=r[fm2].std(ddof=0)
        if not np.isfinite(sd) or sd<1e-12: sd=1.0
        resid_z[idx]=((r-mu)/sd).to_numpy()

        d=x.diff(); sg=np.sign(d)
        flip=(sg.ne(sg.shift(1)) & sg.ne(0) & sg.shift(1).ne(0)).astype(float)
        std15=x.rolling(15,min_periods=15).std(ddof=0)
        range15=x.rolling(15,min_periods=15).max()-x.rolling(15,min_periods=15).min()
        flips15=flip.rolling(15,min_periods=15).sum()
        s_thr=std15[fm2].quantile(.995); r_thr=range15[fm2].quantile(.995); f_thr=flips15[fm2].quantile(.995)
        osc[idx]=(((std15.to_numpy()>=s_thr)&(flips15.to_numpy()>=f_thr)) |
                  ((range15.to_numpy()>=r_thr)&(flips15.to_numpy()>=f_thr)))
        rcode[idx]=rc

    @njit
    def stage1_events(z, osc_mask, rcode, k=0.2, h=8.0, refractory=15):
        n=len(z); ev=np.zeros(n,np.bool_); score=np.zeros(n,np.float64)
        up=0.; down=0.; last=-1; cooldown=0
        for i in range(n):
            if rcode[i]!=last:
                up=0.; down=0.; cooldown=0; last=rcode[i]
            if cooldown>0: cooldown-=1
            zi=z[i]
            if np.isfinite(zi):
                up=max(0.,up+zi-k); down=max(0.,down-zi-k)
            score[i]=up+down
            if cooldown==0 and (score[i]>=h or osc_mask[i]):
                ev[i]=True; up=0.; down=0.; cooldown=refractory
        return ev,score

    s1,s1score=stage1_events(resid_z,osc,rcode)

    # Stage2 Rule20 thresholds from fit-normal
    rule20=np.zeros(N,dtype=bool)
    for rid,g in df.groupby('reactor_id',sort=False):
        idx=g.index.to_numpy(); fm=g['split'].eq('fit') & g['fault_type'].eq(0)
        mt=g.loc[fm,'feed_mean_z20'].quantile(.05)
        ft=g.loc[fm,'feed_neg_frac20'].quantile(.90)
        at=g.loc[fm,'feed_neg_area20'].quantile(.90)
        rule20[idx]=((df.loc[idx,'feed_mean_z20'].to_numpy()<=mt) &
                     (df.loc[idx,'feed_neg_frac20'].to_numpy()>=ft) &
                     (df.loc[idx,'feed_neg_area20'].to_numpy()>=at))

    @njit
    def cascade_stage2(stage1, verifier, rcode, wait_min=5, refractory=15):
        n=len(stage1); out=np.zeros(n,np.bool_); parent=np.full(n,-1,np.int64)
        last_final=np.full(32,-10**9,np.int64)
        for i in range(n):
            if not stage1[i]: continue
            rc=rcode[i]; end=min(n-1,i+wait_min)
            for j in range(i,end+1):
                if rcode[j]!=rc: break
                if verifier[j]:
                    if j-last_final[rc]>=refractory:
                        out[j]=True; parent[j]=i; last_final[rc]=j
                    break
        return out,parent

    stage2,parent=cascade_stage2(s1,rule20,rcode,5,15)

    # ------------------------------------------------------------
    # Event-level Stage3 dataset
    # ------------------------------------------------------------
    feat=['feed_mean_z20','temp_slope20_z','coolant_slope20_z']
    valid_stage2_idx=np.where(stage2 & df[feat].notna().all(axis=1).to_numpy())[0]
    events=df.loc[valid_stage2_idx,['timestamp','reactor_id','split','fault_type','episode_id']+feat].copy()
    events['event_idx']=valid_stage2_idx
    events['label_f2']=(events['fault_type']==2).astype(int)
    # Stage3 specifically verifies F2 vs normal; exclude other faults from fitting/tuning.
    train_events=events[(events['split']=='fit') & events['fault_type'].isin([0,2])].copy()
    cal_events=events[(events['split']=='cal') & events['fault_type'].isin([0,2])].copy()
    test_events=events[(events['split']=='test') & events['fault_type'].isin([0,2])].copy()

    print('Stage2 event counts by split/fault:')
    print(events.groupby(['split','fault_type']).size().unstack(fill_value=0))
    print('Fit positives:', int(train_events['label_f2'].sum()), 'fit normal negatives:', int((train_events['label_f2']==0).sum()))

    # Models
    models={}
    models['logistic']=Pipeline([
        ('scaler',StandardScaler()),
        ('lr',LogisticRegression(C=0.5,class_weight='balanced',max_iter=2000,random_state=42))
    ])
    if HAVE_XGB:
        pos=max(1,int(train_events['label_f2'].sum())); neg=max(1,int((train_events['label_f2']==0).sum()))
        models['xgboost']=XGBClassifier(
            n_estimators=120,max_depth=2,learning_rate=0.04,
            subsample=.8,colsample_bytree=1.0,min_child_weight=4,
            reg_alpha=.5,reg_lambda=3.0,
            objective='binary:logistic',eval_metric='logloss',
            scale_pos_weight=neg/pos,random_state=42,n_jobs=4
        )

    for name,m in models.items():
        m.fit(train_events[feat],train_events['label_f2'])
        for evdf in [events,train_events,cal_events,test_events]:
            if len(evdf):
                evdf[name+'_score']=m.predict_proba(evdf[feat])[:,1]

    # ------------------------------------------------------------
    # Evaluation helpers
    # ------------------------------------------------------------
    def split_days(split_name):
        total=0.
        for rid,g in df[df['split'].eq(split_name)].groupby('reactor_id'):
            total += (g['timestamp'].max()-g['timestamp'].min()).total_seconds()/86400 + 1/1440
        return total

    def f2_episodes(split_name):
        rows=[]
        for eid,g in df[df['fault_type'].eq(2)].groupby('episode_id'):
            onset=int(g.index.min())
            if df.loc[onset,'split']==split_name:
                rows.append((int(eid),df.loc[onset,'reactor_id'],onset,df.loc[onset,'timestamp']))
        return rows

    def evaluate_event_subset(evsub, split_name):
        # evsub is Stage2 events retained by Stage3 threshold
        normal=evsub[(evsub['split']==split_name)&(evsub['fault_type']==0)]
        fa_day=len(normal)/split_days(split_name)
        delays=[]; ep_rows=[]
        for eid,rid,onset,ts in f2_episodes(split_name):
            z=evsub[(evsub['split']==split_name)&(evsub['fault_type']==2)&(evsub['episode_id']==eid)&(evsub['event_idx']>=onset)]
            if len(z):
                delay=int(z['event_idx'].min()-onset); delays.append(delay)
            else: delay=np.nan
            ep_rows.append({'episode_id':eid,'reactor_id':rid,'onset':ts,'delay_min':delay})
        d=np.array([x for x in delays if np.isfinite(x)])
        return {
            'false_per_reactor_day':fa_day,
            'detected':len(d),'total':len(ep_rows),
            'within15':float(np.mean(d<=15)) if len(d) else 0.,
            'within30':float(np.mean(d<=30)) if len(d) else 0.,
            'median_delay':float(np.median(d)) if len(d) else np.nan,
            'delays':'|'.join(str(int(x)) for x in d)
        }, pd.DataFrame(ep_rows)

    # baseline Stage2
    base_test,base_eps=evaluate_event_subset(events,'test')
    base_cal,_=evaluate_event_subset(events,'cal')
    summary=[{'model':'Stage2_baseline','fa_target':np.nan,'threshold':np.nan,
              'cal_fa_day':base_cal['false_per_reactor_day'],
              'test_fa_day':base_test['false_per_reactor_day'],
              'test_detected':base_test['detected'],'test_total':base_test['total'],
              'within15':base_test['within15'],'within30':base_test['within30'],
              'median_delay':base_test['median_delay'],'test_delays':base_test['delays']}]
    all_ep=[base_eps.assign(model='Stage2_baseline',fa_target=np.nan,threshold=np.nan)]

    # Threshold selection uses CAL NORMAL ONLY: choose smallest threshold with <= target FA/day.
    targets=[0.25,0.5,1.0,2.0,3.0,5.0]
    for name in models:
        scorecol=name+'_score'
        calnorm=cal_events[cal_events['fault_type']==0][scorecol].dropna().to_numpy()
        desc=np.sort(calnorm)[::-1]
        cal_days=split_days('cal')
        for target in targets:
            allowed=int(np.floor(target*cal_days + 1e-12))
            if len(desc)==0 or allowed>=len(desc):
                chosen=0.0
            elif allowed<=0:
                chosen=float(np.nextafter(desc[0], np.inf))
            else:
                # Exclude the (allowed+1)-th largest normal score; ties may make this conservative.
                chosen=float(np.nextafter(desc[allowed], np.inf))
            test_kept=test_events[test_events[scorecol]>=chosen]
            cal_kept=cal_events[cal_events[scorecol]>=chosen]
            tev,teps=evaluate_event_subset(test_kept,'test')
            cev,_=evaluate_event_subset(cal_kept,'cal')
            summary.append({'model':name,'fa_target':target,'threshold':chosen,
                            'cal_fa_day':cev['false_per_reactor_day'],'test_fa_day':tev['false_per_reactor_day'],
                            'test_detected':tev['detected'],'test_total':tev['total'],
                            'within15':tev['within15'],'within30':tev['within30'],
                            'median_delay':tev['median_delay'],'test_delays':tev['delays']})
            all_ep.append(teps.assign(model=name,fa_target=target,threshold=chosen))

    summary_df=pd.DataFrame(summary)
    ep_df=pd.concat(all_ep,ignore_index=True)
    summary_df.to_csv(os.path.join(OUT,'stage3_summary.csv'),index=False)
    ep_df.to_csv(os.path.join(OUT,'stage3_episode_results.csv'),index=False)
    events.to_csv(os.path.join(OUT,'all_stage2_events_with_stage3_scores.csv'),index=False)

    # Model interpretation
    coef_rows=[]
    if 'logistic' in models:
        co=models['logistic'].named_steps['lr'].coef_[0]
        for f,c in zip(feat,co): coef_rows.append({'model':'logistic','feature':f,'importance':c})
    if 'xgboost' in models:
        for f,c in zip(feat,models['xgboost'].feature_importances_): coef_rows.append({'model':'xgboost','feature':f,'importance':c})
    pd.DataFrame(coef_rows).to_csv(os.path.join(OUT,'stage3_feature_importance.csv'),index=False)

    # Diagnostic: fit/cal/test score summaries
    score_rows=[]
    for name in models:
        sc=name+'_score'
        for spl in ['fit','cal','test']:
            for ft,label in [(0,'normal'),(2,'F2')]:
                z=events[(events['split']==spl)&(events['fault_type']==ft)][sc]
                if len(z):
                    score_rows.append({'model':name,'split':spl,'class':label,'n':len(z),'mean':z.mean(),'median':z.median(),'q10':z.quantile(.1),'q90':z.quantile(.9)})
    pd.DataFrame(score_rows).to_csv(os.path.join(OUT,'stage3_score_distributions.csv'),index=False)

    print('\n=== Stage3 Summary ===')
    print(summary_df.to_string(index=False))
    print('\nFeature importance:')
    print(pd.DataFrame(coef_rows).to_string(index=False))
    print('\nSaved to',OUT)


# ==============================================================================
# 03_f4_fast_verifier
# ==============================================================================
def run_f4_specialist():
    import os, numpy as np, pandas as pd
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    from numba import njit

    DATA=str(WORKSPACE) + '/chemical_process_timeseries.csv'
    OUT=str(WORKSPACE) + '/f4_fast_verifier_outputs'; os.makedirs(OUT,exist_ok=True)
    S=['vibration_rms','motor_current','power_consumption_kw','agitator_speed_rpm']
    df=pd.read_csv(DATA,usecols=['timestamp','reactor_id','fault_type']+S,parse_dates=['timestamp']).sort_values(['reactor_id','timestamp']).reset_index(drop=True)
    for c in S: df[c]=df.groupby('reactor_id')[c].transform(lambda s:s.interpolate(limit_direction='both'))
    # split
    sp=np.empty(len(df),dtype=object)
    for rid,g in df.groupby('reactor_id',sort=False):
        n=len(g); a=int(.45*n); b=int(.60*n); z=np.full(n,'test',dtype=object); z[:a]='fit'; z[a:b]='cal'; sp[g.index]=z
    df['split']=sp
    ne=(df.fault_type.ne(df.groupby('reactor_id').fault_type.shift())|df.reactor_id.ne(df.reactor_id.shift())); df['episode_id']=ne.cumsum().astype(int)
    N=len(df); idxall=np.arange(N); reactors=list(df.reactor_id.drop_duplicates()); rcode=np.full(N,-1,np.int16)
    # causal z and compact features
    for rc,rid in enumerate(reactors):
        idx=df.index[df.reactor_id.eq(rid)]; g=df.loc[idx]; rcode[idx]=rc
        for s in S:
            x=g[s].astype(float); mean30=x.shift(1).rolling(30,min_periods=30).mean(); sd30=x.shift(1).rolling(30,min_periods=30).std(ddof=0).replace(0,np.nan); z=(x-mean30)/sd30
            df.loc[idx,f'{s}_z']=z.to_numpy()
            for w in [10,15,20,30]: df.loc[idx,f'{s}_mean{w}']=z.rolling(w,min_periods=w).mean().to_numpy()
            if s=='vibration_rms':
                for w in [10,15,20,30]:
                    # rolling slope via pandas rolling apply on only 6 reactors, acceptable
                    xx=np.arange(w); xm=xx.mean(); den=np.sum((xx-xm)**2)
                    arr=z.to_numpy(); out=np.full(len(arr),np.nan)
                    # convolution formula: slope=sum((x-xm)y)/den
                    kernel=(xx-xm)[::-1]
                    conv=np.convolve(np.nan_to_num(arr,nan=0.0),kernel,mode='valid')/den
                    out[w-1:]=conv
                    cnt=pd.Series(arr).notna().rolling(w,min_periods=w).sum().to_numpy(); out[cnt<w]=np.nan
                    df.loc[idx,f'vib_slope{w}']=out
                    df.loc[idx,f'vib_posfrac{w}']=(z>0).astype(float).rolling(w,min_periods=w).mean().to_numpy()

    split_arr=df.split.to_numpy(); fault=df.fault_type.to_numpy(); ep=df.episode_id.to_numpy()
    @njit
    def eventize(cond,rcode,refr=15):
        out=np.zeros(len(cond),np.bool_); last=-1; cd=0
        for i in range(len(cond)):
            if rcode[i]!=last: last=rcode[i]; cd=0
            if cd>0: cd-=1
            if cond[i] and cd==0: out[i]=True; cd=refr
        return out

    def days(splitname):
        total=0.
        for rid,g in df[df.split.eq(splitname)].groupby('reactor_id'):
            total+=(g.timestamp.max()-g.timestamp.min()).total_seconds()/86400+1/1440
        return total

    def episodes(splitname):
        out=[]
        for eid,g in df[df.fault_type.eq(4)].groupby('episode_id'):
            onset=int(g.index.min())
            if df.loc[onset,'split']==splitname: out.append((int(eid),df.loc[onset,'reactor_id'],onset))
        return out

    def evaluate(ev,splitname):
        sm=(split_arr==splitname); fa=(ev&sm&(fault==0)).sum()/days(splitname); rows=[]
        for eid,rid,onset in episodes(splitname):
            ids=np.where(ev & sm & (ep==eid)&(fault==4)&(idxall>=onset))[0]
            rows.append((eid,rid,np.nan if len(ids)==0 else int(ids[0]-onset)))
        return fa,rows

    # normal quantile rule grid, reactor-specific
    fm_global=df.split.eq('fit') & df.fault_type.eq(0)
    qs=[.90,.95,.975,.99,.995,.999]
    configs=[]
    # feature templates: single or OR/AND combos
    for q in qs:
        thresholds={}
        for rid,g in df.groupby('reactor_id',sort=False):
            fm=fm_global.loc[g.index]
            thresholds[rid]={
                'mean15':g.loc[fm,'vibration_rms_mean15'].quantile(q),
                'mean20':g.loc[fm,'vibration_rms_mean20'].quantile(q),
                'mean30':g.loc[fm,'vibration_rms_mean30'].quantile(q),
                'slope10':g.loc[fm,'vib_slope10'].quantile(q),
                'slope15':g.loc[fm,'vib_slope15'].quantile(q),
                'slope20':g.loc[fm,'vib_slope20'].quantile(q),
                'pos20':g.loc[fm,'vib_posfrac20'].quantile(q),
            }
        for rule in ['mean15','mean20','mean30','slope10','slope15','slope20','mean20_OR_slope15','mean20_AND_slope15','mean20_OR_pos20']:
            cond=np.zeros(N,bool)
            for rid,g in df.groupby('reactor_id',sort=False):
                ii=g.index.to_numpy(); th=thresholds[rid]
                if rule in th: c=df.loc[ii,('vib_'+rule if rule.startswith('slope') else 'vibration_rms_'+rule)].to_numpy()>=th[rule]
                elif rule=='mean20_OR_slope15': c=(df.loc[ii,'vibration_rms_mean20'].to_numpy()>=th['mean20'])|(df.loc[ii,'vib_slope15'].to_numpy()>=th['slope15'])
                elif rule=='mean20_AND_slope15': c=(df.loc[ii,'vibration_rms_mean20'].to_numpy()>=th['mean20'])&(df.loc[ii,'vib_slope15'].to_numpy()>=th['slope15'])
                elif rule=='mean20_OR_pos20': c=(df.loc[ii,'vibration_rms_mean20'].to_numpy()>=th['mean20'])|(df.loc[ii,'vib_posfrac20'].to_numpy()>=th['pos20'])
                cond[ii]=np.nan_to_num(c,nan=False)
            ev=eventize(cond,rcode,15); cfa,ce=evaluate(ev,'cal'); tfa,te=evaluate(ev,'test'); cd=[x[2] for x in ce if np.isfinite(x[2])]; td=[x[2] for x in te if np.isfinite(x[2])]
            configs.append({'method':'rule','rule':rule,'q':q,'cal_fa_day':cfa,'cal_delay':cd[0] if cd else np.nan,'test_fa_day':tfa,'test_detected':len(td),'test_within15':np.mean(np.array(td)<=15) if td else 0.,'test_within30':np.mean(np.array(td)<=30) if td else 0.,'test_median':np.median(td) if td else np.nan,'test_delays':'|'.join(str(int(x)) for x in td)})
    rulegrid=pd.DataFrame(configs)

    # Logistic regression compact causal features
    features=['vibration_rms_mean10','vibration_rms_mean15','vibration_rms_mean20','vib_slope10','vib_slope15','vib_slope20','vib_posfrac15','vib_posfrac20','motor_current_mean15','motor_current_mean20','power_consumption_kw_mean15','power_consumption_kw_mean20']
    valid=df[features].notna().all(axis=1).to_numpy(); posmask=np.zeros(N,bool)
    for eid,g in df[df.fault_type.eq(4)].groupby('episode_id'):
        onset=int(g.index.min())
        if df.loc[onset,'split']!='fit': continue
        posmask[onset:min(onset+60,int(g.index.max()))+1]=True
    posidx=np.where(valid&posmask)[0]; rng=np.random.default_rng(42); neg=[]
    for rid,g in df[df.split.eq('fit')&df.fault_type.eq(0)&pd.Series(valid,index=df.index)].groupby('reactor_id'):
        ids=g.index.to_numpy(); neg.append(rng.choice(ids,size=min(10000,len(ids)),replace=False))
    negidx=np.concatenate(neg); trainidx=np.concatenate([posidx,negidx]); y=np.concatenate([np.ones(len(posidx),int),np.zeros(len(negidx),int)])
    model=Pipeline([('sc',StandardScaler()),('lr',LogisticRegression(max_iter=1500,class_weight='balanced',C=.5,random_state=42))]); model.fit(df.loc[trainidx,features],y)
    score=np.full(N,np.nan); score[valid]=model.predict_proba(df.loc[valid,features])[:,1]
    calnorm=score[(split_arr=='cal')&(fault==0)&np.isfinite(score)]; ths=sorted(set(list(np.quantile(calnorm,[.90,.95,.975,.99,.995,.9975,.999,.9995]))+[.5,.7,.8,.9,.95,.97,.98,.99,.995]))
    lrrows=[]
    for thr in ths:
        ev=eventize(np.isfinite(score)&(score>=thr),rcode,15); cfa,ce=evaluate(ev,'cal'); tfa,te=evaluate(ev,'test'); cd=[x[2] for x in ce if np.isfinite(x[2])]; td=[x[2] for x in te if np.isfinite(x[2])]
        lrrows.append({'method':'logistic','threshold':float(thr),'cal_fa_day':cfa,'cal_delay':cd[0] if cd else np.nan,'test_fa_day':tfa,'test_detected':len(td),'test_within15':np.mean(np.array(td)<=15) if td else 0.,'test_within30':np.mean(np.array(td)<=30) if td else 0.,'test_median':np.median(td) if td else np.nan,'test_delays':'|'.join(str(int(x)) for x in td)})
    lrgrid=pd.DataFrame(lrrows)
    co=pd.DataFrame({'feature':features,'coef':model.named_steps['lr'].coef_[0]}); co['abscoef']=co.coef.abs(); co=co.sort_values('abscoef',ascending=False)

    # select target operating points using CAL only (<= target FA and cal delay <=30 preferred)
    sel=[]
    for target in [.5,1,2,5,10]:
        for name,g in [('rule',rulegrid),('logistic',lrgrid)]:
            x=g[(g.cal_fa_day<=target)&(g.cal_delay<=30)].copy()
            if not len(x): x=g[g.cal_fa_day<=target].copy()
            if not len(x): continue
            r=x.sort_values(['cal_delay','cal_fa_day'],ascending=[True,False]).iloc[0].to_dict(); r['target_fa_day']=target; sel.append(r)
    sel=pd.DataFrame(sel)

    rulegrid.to_csv(os.path.join(OUT,'rule_grid.csv'),index=False); lrgrid.to_csv(os.path.join(OUT,'logistic_grid.csv'),index=False); sel.to_csv(os.path.join(OUT,'selected_operating_points.csv'),index=False); co.to_csv(os.path.join(OUT,'lr_coefficients.csv'),index=False)
    print('F4 split episodes:',episodes('fit'),episodes('cal'),episodes('test'))
    print('\nSELECTED')
    print(sel.round(3).to_string(index=False))
    print('\nBEST RULE DESCRIPTIVE TEST')
    print(rulegrid.sort_values(['test_within30','test_fa_day','test_median'],ascending=[False,True,True]).head(15).round(3).to_string(index=False))
    print('\nBEST LR DESCRIPTIVE TEST')
    print(lrgrid.sort_values(['test_within30','test_fa_day','test_median'],ascending=[False,True,True]).head(15).round(3).to_string(index=False))
    print('\nCOEFS')
    print(co.head(10).round(3).to_string(index=False))


# ==============================================================================
# 04_integrated_specialists_v1
# ==============================================================================
def run_integrated_specialists():
    import os, math, warnings
    warnings.filterwarnings('ignore')
    import numpy as np
    import pandas as pd
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression

    DATA=str(WORKSPACE) + '/chemical_process_timeseries.csv'
    OUT=str(WORKSPACE) + '/integrated_specialists_v1_outputs'
    os.makedirs(OUT,exist_ok=True)

    # ------------------------------------------------------------
    # Base data + common chronological split / episode metadata
    # ------------------------------------------------------------
    base_cols=['timestamp','reactor_id','fault_type','vibration_rms','motor_current','power_consumption_kw','agitator_speed_rpm']
    df=pd.read_csv(DATA,usecols=base_cols,parse_dates=['timestamp']).sort_values(['reactor_id','timestamp']).reset_index(drop=True)
    for c in ['vibration_rms','motor_current','power_consumption_kw','agitator_speed_rpm']:
        df[c]=df.groupby('reactor_id')[c].transform(lambda s:s.interpolate(limit_direction='both'))

    split=np.empty(len(df),dtype=object)
    for rid,g in df.groupby('reactor_id',sort=False):
        n=len(g); a=int(.45*n); b=int(.60*n)
        arr=np.full(n,'test',dtype=object); arr[:a]='fit'; arr[a:b]='cal'; split[g.index]=arr
    df['split']=split
    new_ep=(df.fault_type.ne(df.groupby('reactor_id').fault_type.shift()) | df.reactor_id.ne(df.reactor_id.shift()))
    df['episode_id']=new_ep.cumsum().astype(int)
    N=len(df); idxall=np.arange(N)
    reactors=list(df.reactor_id.drop_duplicates())
    rcode=np.full(N,-1,np.int16)
    for rc,rid in enumerate(reactors): rcode[df.index[df.reactor_id.eq(rid)]]=rc

    # test exposure
    TEST_DAYS=0.0; TEST_NORMAL_DAYS=0.0
    for rid,g in df[df.split.eq('test')].groupby('reactor_id'):
        TEST_DAYS += (g.timestamp.max()-g.timestamp.min()).total_seconds()/86400 + 1/1440
        TEST_NORMAL_DAYS += (g.fault_type.eq(0).sum()/1440.0)

    # ------------------------------------------------------------
    # Thermal F1/F3 specialist: fixed selected fast Stage1 event stream
    # ------------------------------------------------------------
    thermal_path=str(WORKSPACE) + '/thermal_multicusum_normalml_outputs/test_candidate_events.csv'
    th=pd.read_csv(thermal_path)
    th_events=th[['idx','reactor_id','pred','true_fault','p_F3']].copy()
    th_events=th_events.rename(columns={'pred':'pred_fault'})
    th_events['idx']=th_events['idx'].astype(int)
    th_events['specialist']='thermal_F1F3'
    th_events['score']=np.where(th_events.pred_fault.eq(3), th_events.p_F3, 1-th_events.p_F3)
    th_events['timestamp']=df.loc[th_events.idx,'timestamp'].to_numpy()
    th_events['true_fault_base']=df.loc[th_events.idx,'fault_type'].to_numpy()
    th_events['episode_id']=df.loc[th_events.idx,'episode_id'].to_numpy()
    th_events['split']='test'

    # ------------------------------------------------------------
    # F2 specialist: fixed Stage2 events + train feed/coolant LR on FIT; threshold from CAL normal for 1/day.
    # ------------------------------------------------------------
    f2_ev_path=str(WORKSPACE) + '/integration_work/f2_stage3_3feature_verifier/all_stage2_events_with_stage3_scores.csv'
    if not os.path.exists(f2_ev_path):
        raise FileNotFoundError(f2_ev_path)
    f2all=pd.read_csv(f2_ev_path,parse_dates=['timestamp'])
    f2feat=['feed_mean_z20','coolant_slope20_z']
    train=f2all[(f2all['split']=='fit') & f2all.fault_type.isin([0,2])].dropna(subset=f2feat).copy()
    y=train.fault_type.eq(2).astype(int)
    f2model=Pipeline([('sc',StandardScaler()),('m',LogisticRegression(C=.5,class_weight='balanced',max_iter=2000,random_state=42))])
    f2model.fit(train[f2feat],y)
    valid=f2all[f2feat].notna().all(axis=1)
    f2all['feed_coolant_lr_score']=np.nan
    f2all.loc[valid,'feed_coolant_lr_score']=f2model.predict_proba(f2all.loc[valid,f2feat])[:,1]
    calnorm=f2all[(f2all['split']=='cal')&(f2all.fault_type.eq(0))]['feed_coolant_lr_score'].dropna().to_numpy()
    CAL_DAYS=81.0
    allowed=int(np.floor(1.0*CAL_DAYS+1e-12)); desc=np.sort(calnorm)[::-1]
    f2_thr=float(np.nextafter(desc[allowed],np.inf)) if allowed<len(desc) else 0.0
    f2keep=f2all[(f2all['split']=='test') & (f2all.feed_coolant_lr_score>=f2_thr)].copy()
    f2_events=pd.DataFrame({
        'idx':f2keep.event_idx.astype(int),
        'reactor_id':f2keep.reactor_id,
        'pred_fault':2,
        'true_fault':f2keep.fault_type.astype(int),
        'score':f2keep.feed_coolant_lr_score.astype(float),
        'specialist':'feed_F2',
        'timestamp':f2keep.timestamp,
        'episode_id':f2keep.episode_id.astype(int),
        'split':'test',
    })
    f2_events['true_fault_base']=df.loc[f2_events.idx,'fault_type'].to_numpy()

    # ------------------------------------------------------------
    # F4 specialist: exact vibration/current/power LR feature set, threshold = fixed recommended 0.93
    # ------------------------------------------------------------
    S=['vibration_rms','motor_current','power_consumption_kw','agitator_speed_rpm']
    for rid,g in df.groupby('reactor_id',sort=False):
        idx=g.index
        for s in S:
            x=g[s].astype(float)
            mean30=x.shift(1).rolling(30,min_periods=30).mean()
            sd30=x.shift(1).rolling(30,min_periods=30).std(ddof=0).replace(0,np.nan)
            z=(x-mean30)/sd30
            df.loc[idx,f'{s}_z']=z.to_numpy()
            for w in [10,15,20]:
                df.loc[idx,f'{s}_mean{w}']=z.rolling(w,min_periods=w).mean().to_numpy()
            if s=='vibration_rms':
                for w in [10,15,20]:
                    xx=np.arange(w,dtype=float); xm=xx.mean(); den=np.sum((xx-xm)**2)
                    arr=z.to_numpy(); out=np.full(len(arr),np.nan)
                    kernel=(xx-xm)[::-1]
                    conv=np.convolve(np.nan_to_num(arr,nan=0.0),kernel,mode='valid')/den
                    out[w-1:]=conv
                    cnt=pd.Series(arr).notna().rolling(w,min_periods=w).sum().to_numpy(); out[cnt<w]=np.nan
                    df.loc[idx,f'vib_slope{w}']=out
                    df.loc[idx,f'vib_posfrac{w}']=(z>0).astype(float).rolling(w,min_periods=w).mean().to_numpy()

    f4feat=['vibration_rms_mean10','vibration_rms_mean15','vibration_rms_mean20','vib_slope10','vib_slope15','vib_slope20','vib_posfrac15','vib_posfrac20','motor_current_mean15','motor_current_mean20','power_consumption_kw_mean15','power_consumption_kw_mean20']
    valid=df[f4feat].notna().all(axis=1).to_numpy(); posmask=np.zeros(N,bool)
    for eid,g in df[df.fault_type.eq(4)].groupby('episode_id'):
        onset=int(g.index.min())
        if df.loc[onset,'split']!='fit': continue
        posmask[onset:min(onset+60,int(g.index.max()))+1]=True
    posidx=np.where(valid&posmask)[0]
    rng=np.random.default_rng(42); neg=[]
    for rid,g in df[df.split.eq('fit')&df.fault_type.eq(0)&pd.Series(valid,index=df.index)].groupby('reactor_id'):
        ids=g.index.to_numpy(); neg.append(rng.choice(ids,size=min(10000,len(ids)),replace=False))
    negidx=np.concatenate(neg); tridx=np.concatenate([posidx,negidx]); y4=np.concatenate([np.ones(len(posidx),int),np.zeros(len(negidx),int)])
    f4model=Pipeline([('sc',StandardScaler()),('lr',LogisticRegression(max_iter=1500,class_weight='balanced',C=.5,random_state=42))])
    f4model.fit(df.loc[tridx,f4feat],y4)
    f4score=np.full(N,np.nan); f4score[valid]=f4model.predict_proba(df.loc[valid,f4feat])[:,1]
    F4_THR=0.93

    # eventize fixed threshold, refractory 15 min per reactor
    f4_cond=np.isfinite(f4score)&(f4score>=F4_THR)
    f4mask=np.zeros(N,bool)
    for rid,g in df.groupby('reactor_id',sort=False):
        cooldown=0
        for i in g.index.to_numpy():
            if cooldown>0: cooldown-=1
            if f4_cond[i] and cooldown==0:
                f4mask[i]=True; cooldown=15
    f4idx=np.where(f4mask & df.split.eq('test').to_numpy())[0]
    f4_events=pd.DataFrame({
        'idx':f4idx,
        'reactor_id':df.loc[f4idx,'reactor_id'].to_numpy(),
        'pred_fault':4,
        'true_fault':df.loc[f4idx,'fault_type'].to_numpy(int),
        'score':f4score[f4idx],
        'specialist':'mechanical_F4',
        'timestamp':df.loc[f4idx,'timestamp'].to_numpy(),
        'episode_id':df.loc[f4idx,'episode_id'].to_numpy(int),
        'split':'test',
    })
    f4_events['true_fault_base']=f4_events['true_fault']

    # ------------------------------------------------------------
    # Combine all specialist events in parallel (no test-tuned priority)
    # ------------------------------------------------------------
    cols=['idx','timestamp','reactor_id','episode_id','true_fault_base','pred_fault','specialist','score','split']
    events=pd.concat([
        th_events[cols],f2_events[cols],f4_events[cols]
    ],ignore_index=True).sort_values(['idx','specialist']).reset_index(drop=True)
    events=events.rename(columns={'true_fault_base':'true_fault'})
    events.to_csv(os.path.join(OUT,'integrated_test_events.csv'),index=False)

    # Specialist event burden by state
    burden=[]
    for spec,g in events.groupby('specialist'):
        normal_count=int((g.true_fault==0).sum())
        cross_count=int((g.true_fault!=0).sum() - (g.pred_fault==g.true_fault).sum())
        correct_fault_count=int((g.pred_fault==g.true_fault).sum())
        burden.append({'specialist':spec,'normal_false_events':normal_count,'normal_false_per_normal_reactor_day':normal_count/TEST_NORMAL_DAYS,
                       'wrong_class_events_during_faults':cross_count,'correct_class_events_during_faults':correct_fault_count,'total_test_events':len(g)})
    burden=pd.DataFrame(burden)

    # Union exact-minute normal events and globally grouped alert incidents (15-min cooldown per reactor)
    normal_events=events[events.true_fault.eq(0)].copy()
    normal_union=normal_events.drop_duplicates(['reactor_id','idx'])
    # global incident grouping: any alerts within 15 minutes of previous incident are same burden event
    incident_rows=[]
    for rid,g in normal_union.sort_values('idx').groupby('reactor_id'):
        last=-10**9
        for _,r in g.iterrows():
            if int(r.idx)-last>=15:
                incident_rows.append(r)
                last=int(r.idx)
    normal_inc=pd.DataFrame(incident_rows)

    # Cross-fault event confusion counts (event-level)
    conf=(events[events.true_fault.ne(0)]
          .groupby(['true_fault','pred_fault']).size().rename('event_count').reset_index())
    conf_pivot=conf.pivot(index='true_fault',columns='pred_fault',values='event_count').fillna(0).astype(int)
    conf_pivot.to_csv(os.path.join(OUT,'cross_fault_event_confusion.csv'))

    # ------------------------------------------------------------
    # Episode-level integrated evaluation
    # ------------------------------------------------------------
    eprows=[]
    for eid,g in df[(df.split=='test') & (df.fault_type!=0)].groupby('episode_id'):
        ft=int(g.fault_type.iloc[0]); onset=int(g.index.min()); end=int(g.index.max())+1
        rid=g.reactor_id.iloc[0]; ts=g.timestamp.iloc[0]
        eg=events[(events.idx>=onset)&(events.idx<end)&(events.reactor_id==rid)].sort_values('idx')
        correct=eg[eg.pred_fault.eq(ft)]
        wrong=eg[eg.pred_fault.ne(ft)]
        cd=np.nan if len(correct)==0 else int(correct.idx.min()-onset)
        wd=np.nan if len(wrong)==0 else int(wrong.idx.min()-onset)
        first_delay=np.nan; first_preds=''; first_specs=''; first_has_correct=False; first_conflict=False
        if len(eg):
            fi=int(eg.idx.min()); first_delay=fi-onset
            fg=eg[eg.idx.eq(fi)]
            preds=sorted(fg.pred_fault.unique().tolist())
            specs=sorted(fg.specialist.unique().tolist())
            first_preds='|'.join(map(str,preds)); first_specs='|'.join(specs)
            first_has_correct=ft in preds
            first_conflict=len(preds)>1
        wrong_before=bool(np.isfinite(wd) and (not np.isfinite(cd) or wd<cd))
        simultaneous_wrong_at_correct=False
        if np.isfinite(cd):
            ci=onset+int(cd)
            cg=eg[eg.idx.eq(ci)]
            simultaneous_wrong_at_correct=bool((cg.pred_fault.ne(ft)).any())
        eprows.append({
            'episode_id':int(eid),'reactor_id':rid,'fault':ft,'onset':ts,
            'correct_delay':cd,'wrong_delay':wd,'first_delay':first_delay,
            'first_preds':first_preds,'first_specialists':first_specs,
            'first_has_correct':first_has_correct,'first_conflict':first_conflict,
            'wrong_before_correct':wrong_before,'simultaneous_wrong_at_correct':simultaneous_wrong_at_correct,
            'n_all_alerts_in_episode':len(eg),'n_wrong_alerts_before_correct': int(((wrong.idx < onset+cd).sum()) if np.isfinite(cd) else len(wrong))
        })
    epout=pd.DataFrame(eprows).sort_values(['fault','reactor_id','onset'])
    epout.to_csv(os.path.join(OUT,'integrated_episode_results.csv'),index=False)

    # By fault summary
    summary=[]
    for ft,g in epout.groupby('fault'):
        summary.append({
            'fault':int(ft),'episodes':len(g),'detected_rate':g.correct_delay.notna().mean(),
            'within5':(g.correct_delay<=5).fillna(False).mean(),
            'within15':(g.correct_delay<=15).fillna(False).mean(),
            'within30':(g.correct_delay<=30).fillna(False).mean(),
            'median_correct_delay':g.correct_delay.median(),
            'first_has_correct_rate':g.first_has_correct.mean(),
            'wrong_before_correct_rate':g.wrong_before_correct.mean(),
            'first_conflict_rate':g.first_conflict.mean(),
        })
    allg=epout
    summary.append({
        'fault':'ALL','episodes':len(allg),'detected_rate':allg.correct_delay.notna().mean(),
        'within5':(allg.correct_delay<=5).fillna(False).mean(),
        'within15':(allg.correct_delay<=15).fillna(False).mean(),
        'within30':(allg.correct_delay<=30).fillna(False).mean(),
        'median_correct_delay':allg.correct_delay.median(),
        'first_has_correct_rate':allg.first_has_correct.mean(),
        'wrong_before_correct_rate':allg.wrong_before_correct.mean(),
        'first_conflict_rate':allg.first_conflict.mean(),
    })
    sumdf=pd.DataFrame(summary)

    # Overall integration summary
    overall=pd.DataFrame([{
        'test_reactor_days':TEST_DAYS,
        'test_normal_reactor_days':TEST_NORMAL_DAYS,
        'normal_false_events_raw_sum':len(normal_events),
        'normal_false_events_union_exact_minute':len(normal_union),
        'normal_false_events_union_per_normal_reactor_day':len(normal_union)/TEST_NORMAL_DAYS,
        'normal_global_15m_incidents':len(normal_inc),
        'normal_global_15m_incidents_per_normal_reactor_day':len(normal_inc)/TEST_NORMAL_DAYS,
        'test_fault_episodes':len(epout),
        'all_detected_rate':allg.correct_delay.notna().mean(),
        'all_within15':(allg.correct_delay<=15).fillna(False).mean(),
        'all_within30':(allg.correct_delay<=30).fillna(False).mean(),
        'all_median_correct_delay':allg.correct_delay.median(),
        'all_wrong_before_correct_rate':allg.wrong_before_correct.mean(),
        'all_first_has_correct_rate':allg.first_has_correct.mean(),
        'f2_lr_threshold_cal_1day':f2_thr,
        'f4_lr_threshold_fixed':F4_THR,
    }])

    burden.to_csv(os.path.join(OUT,'specialist_event_burden.csv'),index=False)
    sumdf.to_csv(os.path.join(OUT,'integrated_fault_summary.csv'),index=False)
    overall.to_csv(os.path.join(OUT,'integrated_overall_summary.csv'),index=False)
    normal_union.to_csv(os.path.join(OUT,'normal_false_union_events.csv'),index=False)
    normal_inc.to_csv(os.path.join(OUT,'normal_false_global_15m_incidents.csv'),index=False)

    # compact conflict summary by true fault / specialist
    cross=events[events.true_fault.ne(0)].groupby(['true_fault','specialist']).agg(
        events=('idx','size'),
        correct_events=('pred_fault',lambda s: int((s.to_numpy()==events.loc[s.index,'true_fault'].to_numpy()).sum()))
    ).reset_index()
    cross.to_csv(os.path.join(OUT,'cross_fault_specialist_activity.csv'),index=False)

    # print concise outputs
    print('F2 threshold recomputed:',f2_thr)
    print('TEST days',TEST_DAYS,'normal days',TEST_NORMAL_DAYS)
    print('\nSPECIALIST BURDEN')
    print(burden.to_string(index=False))
    print('\nEPISODES')
    print(epout.to_string(index=False))
    print('\nFAULT SUMMARY')
    print(sumdf.to_string(index=False))
    print('\nOVERALL')
    print(overall.to_string(index=False))
    print('\nCROSS FAULT EVENT CONFUSION')
    print(conf_pivot.to_string())


# ==============================================================================
# 05_thermal_arbitration_v2
# ==============================================================================
def run_thermal_arbitration():
    import os, numpy as np, pandas as pd
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression

    CAND=str(WORKSPACE) + '/thermal_multicusum_normalml_outputs/all_candidate_events.csv'
    EVENTS=str(WORKSPACE) + '/integrated_specialists_v1_outputs/integrated_test_events.csv'
    DATA=str(WORKSPACE) + '/chemical_process_timeseries.csv'
    OUT=str(WORKSPACE) + '/integrated_arbitration_v2'; os.makedirs(OUT,exist_ok=True)

    c=pd.read_csv(CAND).sort_values(['reactor_id','idx']).reset_index(drop=True)
    c['pred_conf']=np.where(c.pred.eq(3),c.p_F3,1-c.p_F3)
    base=['p_F3','pred_conf','log_Ccool','log_Ctemp','log_Pup','log_Pdown','cool_share','temp_share','log_thermal_sum','resid_cool','resid_temp','resid_pressure']
    train=c[(c.split==0)&(((c.true_fault.isin([1,3]))&(c.ep_min<=30))|(c.true_fault==0))].dropna(subset=base).copy()
    pos=train[train.true_fault.isin([1,3])]; neg=train[train.true_fault==0]
    if len(neg)>30000: neg=neg.sample(30000,random_state=42)
    tr=pd.concat([pos,neg],ignore_index=True); y=tr.true_fault.isin([1,3]).astype(int)
    model=Pipeline([('sc',StandardScaler()),('lr',LogisticRegression(C=.25,class_weight='balanced',max_iter=2500,random_state=42))]); model.fit(tr[base],y)
    valid=c[base].notna().all(axis=1); c['vscore']=np.nan; c.loc[valid,'vscore']=model.predict_proba(c.loc[valid,base])[:,1]
    # normal days
    D=pd.read_csv(DATA,usecols=['timestamp','reactor_id','fault_type'],parse_dates=['timestamp']).sort_values(['reactor_id','timestamp']).reset_index(drop=True)
    split=np.empty(len(D),dtype=np.int8)
    for rid,g in D.groupby('reactor_id',sort=False):
     n=len(g); a=int(.45*n); b=int(.60*n); ar=np.full(n,2,np.int8); ar[:a]=0; ar[a:b]=1; split[g.index]=ar
    D['split']=split
    new=(D.fault_type.ne(D.groupby('reactor_id').fault_type.shift())|D.reactor_id.ne(D.reactor_id.shift())); D['episode_id']=new.cumsum().astype(int)
    normal_days=float(((D.split==2)&(D.fault_type==0)).sum()/1440)
    cal_days=float(((D.split==1)&(D.fault_type==0)).sum()/1440)
    calnorm=c[(c.split==1)&(c.true_fault==0)].vscore.dropna().to_numpy(); allowed=max(1,int(np.floor(20*cal_days))); desc=np.sort(calnorm)[::-1]; thr=float(np.nextafter(desc[allowed],np.inf))
    th=c[(c.split==2)&(c.vscore>=thr)].copy(); th=th[['idx','reactor_id','pred','vscore','true_fault','episode_id']].rename(columns={'pred':'pred_fault','vscore':'score'})
    th['specialist']='thermal_provisional'
    strong=pd.read_csv(EVENTS); strong=strong[strong.specialist.isin(['feed_F2','mechanical_F4'])].copy()
    strong=strong[['idx','reactor_id','pred_fault','score','true_fault','episode_id','specialist']]

    # Evaluate arbitration: strong events immediate; thermal provisional clusters held H minutes.
    # If any strong event occurs during hold, cancel thermal cluster. Else emit thermal at expiry,
    # label by confidence-weighted vote among thermal provisionals in window.
    rows=[]; final_all=[]
    for H in [0,5,10,15,20,25]:
     out=[]
     for rid in D.reactor_id.drop_duplicates():
      t=th[th.reactor_id==rid].sort_values('idx').reset_index(drop=True)
      s=strong[strong.reactor_id==rid].sort_values('idx').reset_index(drop=True)
      # strong always emitted
      for _,r in s.iterrows(): out.append({'idx':int(r.idx),'reactor_id':rid,'pred_fault':int(r.pred_fault),'specialist':r.specialist,'score':float(r.score)})
      k=0
      while k<len(t):
       start=int(t.loc[k,'idx']); end=start+H
       j=k
       while j+1<len(t) and int(t.loc[j+1,'idx'])<=end: j+=1
       # cancel if F2/F4 strong happens within [start,end]
       sg=s[(s.idx>=start)&(s.idx<=end)]
       if len(sg)==0:
        seg=t.iloc[k:j+1]
        # confidence-weighted vote
        w1=float(seg.loc[seg.pred_fault==1,'score'].sum()); w3=float(seg.loc[seg.pred_fault==3,'score'].sum())
        pred=1 if w1>=w3 else 3
        score=max(w1,w3)/(w1+w3+1e-9)
        out.append({'idx':end,'reactor_id':rid,'pred_fault':pred,'specialist':'thermal_after_hold','score':score})
       k=j+1
     final=pd.DataFrame(out).sort_values(['idx','specialist']).reset_index(drop=True)
     # enrich truth
     final['true_fault']=D.loc[final.idx.clip(upper=len(D)-1).astype(int),'fault_type'].to_numpy()
     final['episode_id']=D.loc[final.idx.clip(upper=len(D)-1).astype(int),'episode_id'].to_numpy()
     final['hold']=H
     final_all.append(final)
     # normal false burden (events; exact minute duplicates count separately? union by reactor+idx)
     nfalse=len(final[final.true_fault==0].drop_duplicates(['reactor_id','idx']))
     # episode eval
     epr=[]
     for eid,g in D[(D.split==2)&(D.fault_type!=0)].groupby('episode_id'):
      onset=int(g.index.min()); endidx=int(g.index.max()); ft=int(g.fault_type.iloc[0]); rid0=g.reactor_id.iloc[0]
      eg=final[(final.reactor_id==rid0)&(final.idx>=onset)&(final.idx<=endidx)].sort_values('idx')
      cor=eg[eg.pred_fault==ft]; wrong=eg[eg.pred_fault!=ft]
      cd=np.nan if len(cor)==0 else int(cor.idx.min()-onset); wd=np.nan if len(wrong)==0 else int(wrong.idx.min()-onset)
      wb=bool(np.isfinite(wd) and (not np.isfinite(cd) or wd<cd))
      epr.append((eid,ft,rid0,cd,wd,wb))
     ep=pd.DataFrame(epr,columns=['episode_id','fault','reactor_id','correct_delay','wrong_delay','wrong_before_correct'])
     arr=ep.correct_delay.dropna().to_numpy()
     rows.append({'hold_min':H,'normal_false_per_day':nfalse/normal_days,'detected':len(arr),'episodes':len(ep),'within15':np.mean(arr<=15),'within30':np.mean(arr<=30),'median_delay':np.median(arr),'wrong_before_rate':ep.wrong_before_correct.mean(),'thermal_threshold':thr})
     ep.to_csv(f'{OUT}/episode_results_hold{H}.csv',index=False)

    R=pd.DataFrame(rows); R.to_csv(f'{OUT}/arbitration_summary.csv',index=False); pd.concat(final_all,ignore_index=True).to_csv(f'{OUT}/final_events_all_holds.csv',index=False)
    print('thermal point LR threshold target20/day cal=',thr)
    print('thermal provisional test normal/day=',len(th[(th.true_fault==0)])/normal_days)
    print(R.to_string(index=False))


# ============================================================================== 
# Command-line entry point
# ============================================================================== 
def main():
    parser = argparse.ArgumentParser(
        description='Standalone specialist-based chemical fault diagnosis pipeline.'
    )
    parser.add_argument('--workspace', default='./fault_run', help='Directory for generated outputs')
    parser.add_argument(
        '--stop-after',
        choices=['thermal','f2','f4','integration','arbitration'],
        default='arbitration',
        help='Run only through the selected stage.'
    )
    parser.add_argument(
        '--validate-only',
        action='store_true',
        help='Only load/preprocess the raw CSV and write dataset summaries.'
    )
    args = parser.parse_args()

    # ==========================================================================
    # STEP 1. ORIGINAL CSV LOAD + COMMON PREPROCESSING
    # ==========================================================================
    df = load_raw_csv(DATA_FILE)
    prepare_workspace_from_raw(df, args.workspace)

    if args.validate_only:
        print('\n[VALIDATION DONE]')
        print('Workspace:', WORKSPACE)
        print('Dataset summary:', WORKSPACE / 'dataset_split_fault_summary.csv')
        print('Episode summary:', WORKSPACE / 'episode_summary.csv')
        return

    # ==========================================================================
    # STEP 2. F1/F3 THERMAL SPECIALIST
    # ==========================================================================
    print('\n[2/6] F1/F3 thermal specialist')
    run_thermal_f1_f3()
    if args.stop_after == 'thermal':
        return

    # ==========================================================================
    # STEP 3. F2 FEED SPECIALIST
    # ==========================================================================
    print('\n[3/6] F2 specialist')
    run_f2_specialist()
    if args.stop_after == 'f2':
        return

    # ==========================================================================
    # STEP 4. F4 MECHANICAL SPECIALIST
    # ==========================================================================
    print('\n[4/6] F4 specialist')
    run_f4_specialist()
    if args.stop_after == 'f4':
        return

    # ==========================================================================
    # STEP 5. SPECIALIST INTEGRATION
    # ==========================================================================
    print('\n[5/6] Specialist integration')
    _prepare_integration_inputs()
    run_integrated_specialists()
    if args.stop_after == 'integration':
        return

    # ==========================================================================
    # STEP 6. THERMAL ARBITRATION / FINAL EVENT STREAM
    # ==========================================================================
    print('\n[6/6] Thermal arbitration')
    run_thermal_arbitration()

    print('\n[DONE]')
    print('Workspace:', WORKSPACE)
    print('Integration summary:', WORKSPACE / 'integrated_specialists_v1_outputs' / 'integrated_overall_summary.csv')
    print('Arbitration summary:', WORKSPACE / 'integrated_arbitration_v2' / 'arbitration_summary.csv')
    print('Recommended hold=0 episodes:', WORKSPACE / 'integrated_arbitration_v2' / 'episode_results_hold0.csv')


if __name__ == '__main__':
    main()
