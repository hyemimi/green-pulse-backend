import { Module } from '@nestjs/common';
import { EsgModule } from '../esg/esg.module';
import { ReportsController } from './reports.controller';
import { ReportsService } from './reports.service';

@Module({
  imports: [EsgModule],
  controllers: [ReportsController],
  providers: [ReportsService],
})
export class ReportsModule {}