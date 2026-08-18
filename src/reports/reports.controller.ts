import { Controller, Get, Query, Res } from '@nestjs/common';
import { ApiOperation, ApiProduces, ApiQuery, ApiTags } from '@nestjs/swagger';
import type { Response } from 'express';
import { ReportsService } from './reports.service';

@ApiTags('reports')
@Controller('api/reports')
export class ReportsController {
  constructor(private readonly reportsService: ReportsService) {}

  @Get('esg.docx')
  @ApiOperation({ summary: 'ESG 절감 성과를 워드(.docx) 문서로 다운로드' })
  @ApiProduces('application/vnd.openxmlformats-officedocument.wordprocessingml.document')
  @ApiQuery({ name: 'runId', required: false })
  @ApiQuery({ name: 'from', required: false, example: '2024-01-01' })
  @ApiQuery({ name: 'to', required: false, example: '2024-03-31' })
  @ApiQuery({ name: 'reactorId', required: false, example: 'A_R1' })
  @ApiQuery({ name: 'holdMin', required: false, example: 0 })
  async downloadEsgReport(
    @Res() res: Response,
    @Query('runId') runId?: string,
    @Query('from') from?: string,
    @Query('to') to?: string,
    @Query('reactorId') reactorId?: string,
    @Query('holdMin') holdMin = '0',
  ) {
    const buffer = await this.reportsService.generateEsgReport({
      runId,
      from,
      to,
      reactorId,
      holdMin: Number(holdMin),
    });

    res.set({
      'Content-Type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'Content-Disposition': 'attachment; filename="esg-report.docx"',
    });
    res.send(buffer);
  }
}