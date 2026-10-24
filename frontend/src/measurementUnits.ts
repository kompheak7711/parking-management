// The fixed measurement unit of each Utility Type (DL-071 answer 9): electricity in kWh and
// water in cubic metres. Meters and Rates recorded before may keep another stored code.
export const MEASUREMENT_UNIT_CODES = {
  ELECTRICITY: "KWH",
  WATER: "M3",
} as const;

const LABELS: Record<string, string> = { KWH: "kWh", M3: "m³" };

export function measurementUnitLabel(code: string): string {
  return LABELS[code] ?? code;
}
