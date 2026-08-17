import { NestFactory } from '@nestjs/core';
import { ConfigService } from '@nestjs/config';
import { AppModule } from './app.module';
import { DocumentBuilder, SwaggerModule } from '@nestjs/swagger';

async function bootstrap() {
  const app = await NestFactory.create(AppModule);
  const config = app.get(ConfigService);

  // 프론트 개발 서버가 별도 포트에서 뜨는 구조를 고려해 CORS를 환경변수로 열어둡니다.
  // 배포 시에는 CORS_ORIGIN을 실제 프론트 도메인으로 제한하면 됩니다.
  app.enableCors({
    origin: config.get<string>('CORS_ORIGIN')?.split(',') ?? true,
    credentials: true,
  });

  // Swagger UI는 프론트 개발자가 API 경로, 쿼리 파라미터, 응답 예시를 바로 확인할 수 있게 해줍니다.
  // 운영 환경에서도 공개할 수 있지만, 내부용이면 Nginx나 인증 계층에서 접근을 제한하는 편이 좋습니다.
  const swaggerConfig = new DocumentBuilder()
    .setTitle('Green-Pulse Backend API')
    .setDescription('Precomputed chemical fault diagnosis results API for the Green-Pulse dashboard.')
    .setVersion('0.1.0')
    .addTag('health', 'Server health check')
    .addTag('dashboard', 'Dashboard summaries and model result APIs')
    .addTag('esg', 'Estimated energy savings and ESG conversion APIs')
    .build();
  const swaggerDocument = SwaggerModule.createDocument(app, swaggerConfig);
  SwaggerModule.setup('api-docs', app, swaggerDocument, {
    jsonDocumentUrl: 'api-docs-json',
  });

  const port = config.get<number>('PORT') ?? 3000;
  await app.listen(port, '0.0.0.0');
  console.log(`Green-Pulse API is running on http://0.0.0.0:${port}`);
}

void bootstrap();
