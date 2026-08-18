import { applyDecorators, Controller, Get, Query } from '@nestjs/common';
import { ApiOkResponse, ApiOperation, ApiQuery, ApiTags } from '@nestjs/swagger';
import { EsgService } from './esg.service';

@ApiTags('esg')
@Controller('api/esg')
export class EsgController {
  constructor(private readonly esgService: EsgService) {}

  @Get('power-saving')
  @ApiOperation({ summary: 'ML 탐지 결과를 이용한 개별 예상 전력 절감량 계산' })
  @ApiQuery({ name: 'reactorId', required: true, example: 'B_R3' })
  @ApiQuery({ name: 'predictedFault', required: true, example: 'F2' })
  @ApiQuery({ name: 'onsetTimestamp', required: true, example: '2024-03-29T04:04:00Z' })
  @ApiQuery({ name: 'detectTimestamp', required: false, example: '2024-03-29T04:19:00Z' })
  @ApiQuery({ name: 'detectMinute', required: false, example: 15 })
  @ApiOkResponse({
    schema: {
      example: {
        reactorId: 'B_R3',
        operatingRegime: 'B',
        predictedFault: 2,
        actualFaultAtDetection: 2,
        faultMatch: true,
        onsetTimestamp: '2024-03-29T04:04:00.000Z',
        detectTimestamp: '2024-03-29T04:19:00.000Z',
        detectMinute: 15,
        wastedPowerKwAtDetection: 0.949614,
        integratedMinutes: 15,
        unmitigatedLossKwh: 38.773997,
        actualLossUntilDetectionKwh: 0.082754,
        savedKwh: 38.691243,
        savingRatePct: 99.79,
      },
    },
  })
  getPowerSaving(
    @Query('reactorId') reactorId: string,
    @Query('predictedFault') predictedFault: string,
    @Query('onsetTimestamp') onsetTimestamp: string,
    @Query('detectTimestamp') detectTimestamp?: string,
    @Query('detectMinute') detectMinute?: string,
  ) {
    return this.esgService.getPowerSaving({
      reactorId,
      predictedFault,
      onsetTimestamp,
      detectTimestamp,
      detectMinute: detectMinute === undefined ? undefined : Number(detectMinute),
    });
  }

  @Get('summary')
  @ApiOperation({ summary: 'DB의 이상 탐지 결과 전체 ESG 절감 성과 요약' })
  @EsgQueryDocs()
  getSummary(
    @Query('runId') runId?: string,
    @Query('from') from?: string,
    @Query('to') to?: string,
    @Query('reactorId') reactorId?: string,
    @Query('holdMin') holdMin = '0',
  ) {
    return this.esgService.getSummary({ runId, from, to, reactorId, holdMin: Number(holdMin) });
  }

  @Get('monthly')
  @ApiOperation({ summary: 'DB의 이상 탐지 결과 월별 에너지·CO2 절감량' })
  @EsgQueryDocs()
  getMonthly(
    @Query('runId') runId?: string,
    @Query('from') from?: string,
    @Query('to') to?: string,
    @Query('reactorId') reactorId?: string,
    @Query('holdMin') holdMin = '0',
  ) {
    return this.esgService.getMonthly({ runId, from, to, reactorId, holdMin: Number(holdMin) });
  }

  @Get('conversion-factors')
  @ApiOperation({ summary: 'ESG 환산계수와 전력 계산 기준 조회' })
  getConversionFactors() {
    return this.esgService.getConversionFactors();
  }
}

function EsgQueryDocs() {
  return applyDecorators(
    ApiQuery({ name: 'runId', required: false, description: '생략하면 최신 모델 실행 결과를 사용합니다.' }),
    ApiQuery({ name: 'from', required: false, example: '2024-01-01' }),
    ApiQuery({ name: 'to', required: false, example: '2024-03-31' }),
    ApiQuery({ name: 'reactorId', required: false, example: 'A_R1' }),
    ApiQuery({ name: 'holdMin', required: false, example: 0 }),
  );
}
