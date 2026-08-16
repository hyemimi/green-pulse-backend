import { Controller, Get, Param, Query } from '@nestjs/common';
import { ApiOkResponse, ApiOperation, ApiParam, ApiQuery, ApiTags } from '@nestjs/swagger';
import { DashboardService } from './dashboard.service';

@ApiTags('dashboard')
@Controller('api')
export class DashboardController {
  constructor(private readonly dashboardService: DashboardService) {}

  @Get('model-runs')
  @ApiOperation({ summary: '적재된 모델 실행 이력 조회' })
  @ApiOkResponse({
    description: 'DB에 import된 Python 모델 실행 결과 목록입니다.',
    schema: {
      example: [
        {
          id: 'fault_run',
          workspacePath: '/Users/hyemi/green-pulse-backend/fault_run',
          status: 'imported',
          dataStartAt: '2024-01-01T00:00:00.000Z',
          dataEndAt: '2025-06-23T23:59:00.000Z',
          importedAt: '2026-08-16T13:00:00.000Z',
          notes: 'Imported from Python fault diagnosis pipeline outputs.',
        },
      ],
    },
  })
  getModelRuns() {
    return this.dashboardService.getModelRuns();
  }

  @Get('dashboard/overview')
  @ApiOperation({ summary: '대시보드 첫 화면용 KPI 조회' })
  @ApiQuery({ name: 'runId', required: false, description: '조회할 모델 실행 ID. 생략하면 최신 run을 사용합니다.' })
  @ApiQuery({ name: 'holdMin', required: false, example: 0, description: 'thermal arbitration hold 값입니다.' })
  @ApiOkResponse({
    description: '모델 실행 정보, 데이터 카운트, 예측 이벤트, 에피소드 성능 요약을 반환합니다.',
    schema: {
      example: {
        run: {
          id: 'fault_run',
          workspacePath: '/Users/hyemi/green-pulse-backend/fault_run',
          status: 'imported',
          dataStartAt: '2024-01-01T00:00:00.000Z',
          dataEndAt: '2025-06-23T23:59:00.000Z',
          importedAt: '2026-08-16T13:00:00.000Z',
          notes: 'Imported from Python fault diagnosis pipeline outputs.',
        },
        data: {
          readingCount: 777600,
          faultReadingCount: 27901,
          normalReadingCount: 749699,
          monthCount: 18,
          reactorCount: 6,
        },
        events: {
          eventCount: 120,
          correctEventCount: 45,
          avgScore: 0.91,
        },
        episodes: {
          episodeCount: 9,
          detectedEpisodeCount: 9,
          within15Count: 7,
          within30Count: 9,
          medianDelayMin: 11,
          wrongBeforeCorrectRate: 0.2222,
        },
        metrics: [
          {
            group: 'arbitration',
            name: 'hold_min',
            value: 0,
            text: null,
          },
        ],
      },
    },
  })
  getOverview(@Query('runId') runId?: string, @Query('holdMin') holdMin = '0') {
    return this.dashboardService.getOverview(runId, Number(holdMin));
  }

  @Get('dashboard/monthly')
  @ApiOperation({ summary: '월 단위 요약 데이터 조회' })
  @ApiQuery({ name: 'runId', required: false, description: '조회할 모델 실행 ID. 생략하면 최신 run을 사용합니다.' })
  @ApiQuery({ name: 'from', required: false, example: '2024-01-01', description: '조회 시작 월 또는 날짜입니다.' })
  @ApiQuery({ name: 'to', required: false, example: '2024-12-31', description: '조회 종료 월 또는 날짜입니다.' })
  @ApiQuery({ name: 'reactorId', required: false, example: 'A_R1', description: '특정 reactor만 조회할 때 사용합니다.' })
  @ApiOkResponse({
    description: '월별 readings 수, 실제 fault readings 수, 예측 이벤트 수, 평균 센서값을 반환합니다.',
    schema: {
      example: [
        {
          month: '2024-01-01T00:00:00.000Z',
          reactorId: 'A_R1',
          readingCount: 44640,
          faultReadingCount: 1200,
          normalReadingCount: 43440,
          predictedEventCount: 4,
          avgReactorTemp: 181.23,
          avgPressure: 15.7,
          avgEfficiencyLossPct: 0.42,
        },
      ],
    },
  })
  getMonthlySummaries(
    @Query('runId') runId?: string,
    @Query('from') from?: string,
    @Query('to') to?: string,
    @Query('reactorId') reactorId?: string,
  ) {
    return this.dashboardService.getMonthlySummaries({ runId, from, to, reactorId });
  }

  @Get('fault-events')
  @ApiOperation({ summary: '모델 예측 fault 이벤트 조회' })
  @ApiQuery({ name: 'runId', required: false, description: '조회할 모델 실행 ID. 생략하면 최신 run을 사용합니다.' })
  @ApiQuery({ name: 'holdMin', required: false, example: 0, description: 'thermal arbitration hold 값입니다.' })
  @ApiQuery({ name: 'reactorId', required: false, example: 'A_R1', description: '특정 reactor 이벤트만 조회합니다.' })
  @ApiQuery({ name: 'from', required: false, example: '2024-01-01', description: '이벤트 조회 시작 시각입니다.' })
  @ApiQuery({ name: 'to', required: false, example: '2024-12-31', description: '이벤트 조회 종료 시각입니다.' })
  @ApiQuery({ name: 'limit', required: false, example: 100, description: '최대 반환 개수입니다. 서버에서 1000개로 제한합니다.' })
  @ApiOkResponse({
    description: 'Python 모델이 생성한 예측 fault event stream입니다. trueFault는 비교/평가용 정답 라벨입니다.',
    schema: {
      example: [
        {
          id: 1,
          eventIndex: 12345,
          eventTime: '2024-01-09T13:45:00.000Z',
          reactorId: 'A_R2',
          predictedFault: 1,
          trueFault: 1,
          specialist: 'thermal_after_hold',
          score: 0.87,
          holdMin: 0,
          episodeId: 17,
        },
      ],
    },
  })
  getFaultEvents(
    @Query('runId') runId?: string,
    @Query('holdMin') holdMin = '0',
    @Query('reactorId') reactorId?: string,
    @Query('from') from?: string,
    @Query('to') to?: string,
    @Query('limit') limit = '200',
  ) {
    return this.dashboardService.getFaultEvents({
      runId,
      holdMin: Number(holdMin),
      reactorId,
      from,
      to,
      limit: Number(limit),
    });
  }

  @Get('episodes')
  @ApiOperation({ summary: '에피소드별 탐지 성능 조회' })
  @ApiQuery({ name: 'runId', required: false, description: '조회할 모델 실행 ID. 생략하면 최신 run을 사용합니다.' })
  @ApiQuery({ name: 'holdMin', required: false, example: 0, description: 'thermal arbitration hold 값입니다.' })
  @ApiOkResponse({
    description: '각 fault episode별 정답 탐지 지연, 오진 지연, 정답 전 오진 여부를 반환합니다.',
    schema: {
      example: [
        {
          episodeId: 17,
          fault: 1,
          reactorId: 'A_R2',
          correctDelayMin: 2,
          wrongDelayMin: null,
          wrongBeforeCorrect: false,
        },
      ],
    },
  })
  getEpisodeResults(@Query('runId') runId?: string, @Query('holdMin') holdMin = '0') {
    return this.dashboardService.getEpisodeResults(runId, Number(holdMin));
  }

  @Get('reactors/:reactorId/readings')
  @ApiOperation({ summary: 'Reactor별 센서 시계열 조회' })
  @ApiParam({ name: 'reactorId', example: 'A_R1', description: '조회할 reactor ID입니다.' })
  @ApiQuery({ name: 'from', required: false, example: '2024-01-01', description: '조회 시작 시각입니다.' })
  @ApiQuery({ name: 'to', required: false, example: '2024-01-02', description: '조회 종료 시각입니다.' })
  @ApiQuery({ name: 'limit', required: false, example: 1440, description: '최대 반환 개수입니다. 서버에서 10000개로 제한합니다.' })
  @ApiOkResponse({
    description: '원본 CSV에서 적재한 reactor 센서 시계열 일부를 반환합니다.',
    schema: {
      example: [
        {
          timestamp: '2024-01-01T00:00:00.000Z',
          reactorId: 'A_R1',
          reactorTemp: 181.13,
          reactorPressure: 15.79,
          feedFlowRate: 101.1,
          coolantFlowRate: 79.15,
          agitatorSpeedRpm: 305.78,
          vibrationRms: 1.47,
          motorCurrent: 45.88,
          powerConsumptionKw: 41.29,
          faultType: 0,
          efficiencyLossPct: 0,
        },
      ],
    },
  })
  getReactorReadings(
    @Param('reactorId') reactorId: string,
    @Query('from') from?: string,
    @Query('to') to?: string,
    @Query('limit') limit = '1440',
  ) {
    return this.dashboardService.getReactorReadings({
      reactorId,
      from,
      to,
      limit: Number(limit),
    });
  }
}
