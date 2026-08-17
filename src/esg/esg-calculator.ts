export type EsgConversionFactors = {
  co2KgPerKwh: number;
  paperCupCo2Kg: number;
  carCo2KgPerKm: number;
  pineTreeCo2KgPerYear: number;
  tissueRollCo2Kg: number;
  electricityPriceKrwPerKwh: number;
  annualEnergyTargetKwh: number;
  version: string;
};

export function convertEnergySaving(energySavedKwh: number, factors: EsgConversionFactors) {
  const co2ReducedKg = energySavedKwh * factors.co2KgPerKwh;

  return {
    energySavedKwh,
    co2ReducedKg,
    costSavedKrw: energySavedKwh * factors.electricityPriceKrwPerKwh,
    equivalents: {
      paperCups: safeDivide(co2ReducedKg, factors.paperCupCo2Kg),
      carDistanceKm: safeDivide(co2ReducedKg, factors.carCo2KgPerKm),
      pineTreesPerYear: safeDivide(co2ReducedKg, factors.pineTreeCo2KgPerYear),
      tissueRolls: safeDivide(co2ReducedKg, factors.tissueRollCo2Kg),
    },
    targetAchievementPct:
      factors.annualEnergyTargetKwh > 0
        ? (energySavedKwh / factors.annualEnergyTargetKwh) * 100
        : null,
  };
}

function safeDivide(value: number, divisor: number) {
  return divisor > 0 ? value / divisor : null;
}
