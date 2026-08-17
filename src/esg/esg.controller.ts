import { applyDecorators, Controller, Get, Query } from '@nestjs/common';
import { ApiOkResponse, ApiOperation, ApiQuery, ApiTags } from '@nestjs/swagger';
import { EsgService } from './esg.service';

@ApiTags('esg')
@Controller('api/esg')
export class EsgController {
  constructor(private readonly esgService: EsgService) {}

  @Get('summary')
  @ApiOperation({ summary: '조회 기간의 ESG 절감 성과 요약' })
  @EsgQueryDocs()
  @ApiOkResponse({
    schema: {
      example: {
        runId: 'fault_run',
        period: { from: '2024-01-01', to: '2024-03-31' },
        reactorId: null,
        measurementMode: 'ESTIMATED',
        savingRecordCount: 27901,
        energySavedKwh: 712.5,
        co2ReducedKg: 323.54625,
        costSavedKrw: 0,
        equivalents: {
          paperCups: 7158.1,
          carDistanceKm: 2311.04,
          pineTreesPerYear: 2.59,
          tissueRolls: 1123.42,
        },
        targetAchievementPct: null,
        factorVersion: 'project-draft-v1',
      },
    },
  })
  getSummary(
    @Query('runId') runId?: string,
    @Query('from') from?: string,
    @Query('to') to?: string,
    @Query('reactorId') reactorId?: string,
  ) {
    return this.esgService.getSummary({ runId, from, to, reactorId });
  }

  @Get('monthly')
  @ApiOperation({ summary: '월별 에너지·CO2 절감량 및 생활지표 환산 결과' })
  @EsgQueryDocs()
  @ApiOkResponse({
    schema: {
      example: [
        {
          month: '2024-01-01',
          savingRecordCount: 1000,
          energySavedKwh: 250,
          co2ReducedKg: 113.525,
          costSavedKrw: 0,
          equivalents: {
            paperCups: 2511.62,
            carDistanceKm: 810.89,
            pineTreesPerYear: 0.91,
            tissueRolls: 394.18,
          },
          cumulativeEnergySavedKwh: 250,
          cumulativeCo2ReducedKg: 113.525,
          cumulativeTargetAchievementPct: null,
          factorVersion: 'project-draft-v1',
        },
      ],
    },
  })
  getMonthly(
    @Query('runId') runId?: string,
    @Query('from') from?: string,
    @Query('to') to?: string,
    @Query('reactorId') reactorId?: string,
  ) {
    return this.esgService.getMonthly({ runId, from, to, reactorId });
  }

  @Get('conversion-factors')
  @ApiOperation({ summary: 'ESG 환산계수와 계산 버전 조회' })
  getConversionFactors() {
    return this.esgService.getConversionFactors();
  }
}

function EsgQueryDocs() {
  return applyDecorators(
    ApiQuery({ name: 'runId', required: false, description: '생략하면 최신 모델 실행을 사용합니다.' }),
    ApiQuery({ name: 'from', required: false, example: '2024-01-01' }),
    ApiQuery({ name: 'to', required: false, example: '2024-03-31' }),
    ApiQuery({ name: 'reactorId', required: false, example: 'A_R1' }),
  );
}
