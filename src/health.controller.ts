import { Controller, Get } from '@nestjs/common';
import { ApiOkResponse, ApiTags } from '@nestjs/swagger';

@ApiTags('health')
@Controller('health')
export class HealthController {
  @Get()
  @ApiOkResponse({
    description: 'API server health status.',
    schema: {
      example: {
        status: 'ok',
        service: 'green-pulse-backend',
        mode: 'precomputed-model-result-api',
      },
    },
  })
  getHealth() {
    return {
      status: 'ok',
      service: 'green-pulse-backend',
      // 모델 서버가 아니라 조회 API라는 점을 명확히 보여주는 간단한 헬스 응답입니다.
      mode: 'precomputed-model-result-api',
    };
  }
}
