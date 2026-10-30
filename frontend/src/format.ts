const DECIMALS: Record<string, number> = { MMK: 0, KHR: 0, USD: 2 };

export function money(amount: number | null | undefined, currency: string, compact = false): string {
  if (amount === null || amount === undefined) return "";
  const d = DECIMALS[currency] ?? 0;
  const major = amount / 10 ** d;
  if (compact && Math.abs(major) >= 1_000_000) return `${currency} ${(major / 1_000_000).toFixed(1)}M`;
  if (compact && Math.abs(major) >= 10_000) return `${currency} ${(major / 1000).toFixed(0)}k`;
  return `${currency} ${major.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d })}`;
}

export const pct = (x: number | null | undefined, digits = 1) =>
  x === null || x === undefined ? "" : `${(x * 100).toFixed(digits)}%`;

export const day = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "";

// Business timestamps show in the lender's time zone, not the viewer's.
let TENANT_TZ: string | undefined;
export const setTenantTz = (tz?: string) => (TENANT_TZ = tz);

export const dateTime = (iso?: string | null, tz: string | undefined = TENANT_TZ) =>
  iso
    ? new Date(iso).toLocaleString("en-GB", {
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: tz,
      })
    : "";

export const BUCKET_LABEL: Record<string, string> = {
  pre_due: "Pre-due",
  "1_7": "1-7",
  "8_30": "8-30",
  "31_60": "31-60",
  "61_90": "61-90",
  "90_plus": "90+",
};

export const ROLE_LABEL: Record<string, string> = {
  head_of_collections: "Head of collections",
  branch_manager: "Branch manager",
  credit_officer: "Credit officer",
  leadership: "Leadership",
};

export const toMinor = (major: number, currency: string) => Math.round(major * 10 ** (DECIMALS[currency] ?? 0));
export const toMajor = (minor: number, currency: string) => minor / 10 ** (DECIMALS[currency] ?? 0);
