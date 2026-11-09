export type ShockChannel = 'production-outage' | 'input-cost';

export interface IndustryNode {
  id: string;
  country: string;
  industry: string;
  industryJa: string;
  isRow: boolean;
  isFinalDemand: boolean;
}

export interface FlowEdge {
  buyer: number;
  seller: number;
  coefficient: number;
}

export interface FlowNetwork {
  nodes: IndustryNode[];
  edges: FlowEdge[];
  nodeIndex: Map<string, number>;
}

export interface RangeInput {
  min: number;
  max: number;
}

export interface ScenarioInput {
  eventId: string;
  title: string;
  channel: ShockChannel;
  seedNodes: string[];
  shock: RangeInput;
  /** Loss-mitigation inputs. Set and disclose as assumptions, never as observations. */
  substitution: RangeInput;
  inventory: RangeInput;
  passThrough: RangeInput;
  seed: number;
  samples: number;
  maxSteps: number;
}

export interface IndustryImpact {
  nodeId: string;
  country: string;
  industry: string;
  industryJa: string;
  step: number;
  p10: number;
  p50: number;
  p90: number;
}

export interface CountryImpact {
  country: string;
  p10: number;
  p50: number;
  p90: number;
  coveredIndustries: number;
  step: number;
}

export interface ScenarioResult {
  input: ScenarioInput;
  summary: {
    samples: number;
    maxPropagationSteps: number;
    channel: ShockChannel;
    distributionLabel: string;
    affectedIndustryCount: number;
  };
  industries: IndustryImpact[];
  countries: CountryImpact[];
}

export interface FirmRecord {
  id: string;
  name: string;
  ticker: string | null;
  sector: string | null;
  listingStatus: string;
  country: string;
  industryNode: string | null;
  tier1FinancialRecordCount: number;
}

export interface OwnershipRecord {
  edge_id: string;
  src_id: string;
  dst_id: string;
  relation_type: string;
  share_pct: number | null;
  dependency_status: 'observed_binary' | 'observed_value' | 'estimated' | 'unknown' | string;
  as_of: string;
  source_tier: number;
  source_ref: string | null;
  extraction: string | null;
  confidence: number;
}

export interface DataManifest {
  schemaVersion: string;
  generatedAt: string;
  datasetSnapshot: string;
  boundaryVintage: string;
  ioModelDefinition: {
    source: string;
    coefficient: string;
    includedSparseCoefficientMinimum: number;
    terminalDemandColumns: string;
    countryAggregation: string;
  };
  counts: Record<string, number | Record<string, number>>;
  dataCatalog: Array<{
    id: string;
    label: string;
    period: string;
    source: string;
    license: string;
    role: string;
  }>;
  checksumsSha256: Record<string, string>;
  exclusions: string[];
}

export interface ScenarioBundle {
  schemaVersion: 'ripple-scenario/1.2';
  codeRevision: string;
  modelVersion: string;
  datasetSnapshot: string;
  datasetGeneratedAt: string;
  datasetChecksumsSha256: Record<string, string>;
  createdAt: string;
  sourceStatus: 'observed-data-plus-explicit-assumptions';
  scenario: ScenarioInput;
  results: ScenarioResult;
  interpretation: string[];
}
