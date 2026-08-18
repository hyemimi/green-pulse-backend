import { Injectable } from '@nestjs/common';
import {
  Document,
  Packer,
  Paragraph,
  TextRun,
  HeadingLevel,
  Table,
  TableRow,
  TableCell,
  WidthType,
} from 'docx';
import { EsgService, EsgQuery } from '../esg/esg.service';

@Injectable()
export class ReportsService {
  constructor(private readonly esgService: EsgService) {}

  async generateEsgReport(query: EsgQuery): Promise<Buffer> {
    const [summary, monthly, reactorLosses] = await Promise.all([
      this.esgService.getSummary(query),
      this.esgService.getMonthly(query),
      this.esgService.getReactorLosses(query),
    ]);

    const doc = new Document({
      sections: [
        {
          children: [
            new Paragraph({ text: 'ESG 에너지 절감 성과 리포트', heading: HeadingLevel.TITLE }),
            new Paragraph({
              children: [new TextRun({ text: `생성일: ${new Date().toLocaleString('ko-KR')}`, italics: true })],
            }),
            new Paragraph({ text: '' }),

            new Paragraph({ text: '핵심 절감 지표', heading: HeadingLevel.HEADING_1 }),
            this.buildKeyValueTable([
              ['절감 에너지', `${summary.energySavedKwh.toFixed(2)} kWh`],
              ['CO2 절감량', `${summary.co2ReducedKg.toFixed(2)} kg`],
              ['비용 절감액', `${summary.costSavedKrw.toLocaleString('ko-KR')} 원`],
              [
                '목표 달성률',
                summary.targetAchievementPct !== null ? `${summary.targetAchievementPct.toFixed(1)}%` : '목표 미설정',
              ],
              ['탐지 건수', `${summary.savingRecordCount}건`],
            ]),
            new Paragraph({ text: '' }),

            new Paragraph({ text: '환산 효과', heading: HeadingLevel.HEADING_1 }),
            this.buildKeyValueTable([
              [
                '소나무 식재 효과',
                summary.equivalents.pineTreesPerYear !== null
                  ? `약 ${summary.equivalents.pineTreesPerYear.toFixed(1)}그루/년`
                  : '-',
              ],
              [
                '승용차 주행거리 환산',
                summary.equivalents.carDistanceKm !== null ? `약 ${summary.equivalents.carDistanceKm.toFixed(1)} km` : '-',
              ],
              [
                '종이컵 환산',
                summary.equivalents.paperCups !== null ? `약 ${Math.round(summary.equivalents.paperCups)}개` : '-',
              ],
              [
                '휴지 롤 환산',
                summary.equivalents.tissueRolls !== null ? `약 ${summary.equivalents.tissueRolls.toFixed(1)}롤` : '-',
              ],
            ]),
            new Paragraph({ text: '' }),

            new Paragraph({ text: '월별 절감 추이', heading: HeadingLevel.HEADING_1 }),
            this.buildMonthlyTable(monthly),
            new Paragraph({ text: '' }),

            new Paragraph({ text: '반응기별 손실/절감', heading: HeadingLevel.HEADING_1 }),
            this.buildReactorTable(reactorLosses.reactors),
            new Paragraph({ text: '' }),

            new Paragraph({
              children: [
                new TextRun({
                  text: `계산 방식: ${summary.calculationMethod} (기준 버전: ${summary.factorVersion})`,
                  size: 18,
                  color: '888888',
                }),
              ],
            }),
          ],
        },
      ],
    });

    return Packer.toBuffer(doc);
  }

  private buildKeyValueTable(rows: [string, string][]) {
    return new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      rows: rows.map(
        ([label, value]) =>
          new TableRow({
            children: [
              new TableCell({
                width: { size: 40, type: WidthType.PERCENTAGE },
                children: [new Paragraph({ children: [new TextRun({ text: label, bold: true })] })],
              }),
              new TableCell({ width: { size: 60, type: WidthType.PERCENTAGE }, children: [new Paragraph(value)] }),
            ],
          }),
      ),
    });
  }

  private buildMonthlyTable(monthly: Awaited<ReturnType<EsgService['getMonthly']>>) {
    const header = new TableRow({
      children: ['월', '절감 에너지(kWh)', 'CO2 절감(kg)', '비용 절감(원)', '누적(kWh)'].map(
        (text) => new TableCell({ children: [new Paragraph({ children: [new TextRun({ text, bold: true })] })] }),
      ),
    });

    const dataRows = monthly.map(
      (row) =>
        new TableRow({
          children: [
            row.month,
            row.energySavedKwh.toFixed(2),
            row.co2ReducedKg.toFixed(2),
            row.costSavedKrw.toLocaleString('ko-KR'),
            row.cumulativeEnergySavedKwh.toFixed(2),
          ].map((text) => new TableCell({ children: [new Paragraph(String(text))] })),
        }),
    );

    return new Table({ width: { size: 100, type: WidthType.PERCENTAGE }, rows: [header, ...dataRows] });
  }

  private buildReactorTable(reactors: Awaited<ReturnType<EsgService['getReactorLosses']>>['reactors']) {
    const header = new TableRow({
      children: ['Reactor', '탐지 건수', '방치 시 손실(kWh)', '예방 손실(kWh)', '절감률(%)'].map(
        (text) => new TableCell({ children: [new Paragraph({ children: [new TextRun({ text, bold: true })] })] }),
      ),
    });

    const dataRows = reactors.map(
      (row) =>
        new TableRow({
          children: [
            row.reactorId,
            String(row.episodeCount),
            row.unmitigatedLossKwh.toFixed(2),
            row.avoidableLossKwh.toFixed(2),
            `${row.savingRatePct.toFixed(1)}%`,
          ].map((text) => new TableCell({ children: [new Paragraph(String(text))] })),
        }),
    );

    return new Table({ width: { size: 100, type: WidthType.PERCENTAGE }, rows: [header, ...dataRows] });
  }
}