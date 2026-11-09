import { describe, expect, it } from 'vitest';
import { simulateScenario } from '../src/engine/simulate';
import type { FlowNetwork, IndustryNode, ScenarioInput } from '../src/engine/types';

const nodes: IndustryNode[] = [
  { id: 'AAA_C26', country: 'AAA', industry: 'C26', industryJa: '電子機器', isRow: false, isFinalDemand: false },
  { id: 'BBB_C27', country: 'BBB', industry: 'C27', industryJa: '電機', isRow: false, isFinalDemand: false },
  { id: 'JPN_C29', country: 'JPN', industry: 'C29', industryJa: '自動車', isRow: false, isFinalDemand: false },
  { id: 'ROW_C26', country: 'ROW', industry: 'C26', industryJa: '電子機器', isRow: true, isFinalDemand: false },
];
const network: FlowNetwork = {
  nodes,
  edges: [
    { seller: 0, buyer: 1, coefficient: 0.5 },
    { seller: 1, buyer: 2, coefficient: 0.4 },
    { seller: 3, buyer: 1, coefficient: 0.9 },
  ],
  nodeIndex: new Map(nodes.map((node, index) => [node.id, index])),
};
const scenario: ScenarioInput = {
  eventId: 'proxy', title: 'Explicitly entered supplier-sector interruption',
  channel: 'production-outage', seedNodes: ['AAA_C26'],
  shock: { min: 0.4, max: 0.6 },
  substitution: { min: 0.2, max: 0.4 },
  inventory: { min: 0.1, max: 0.3 },
  passThrough: { min: 0, max: 0 }, seed: 7, samples: 41, maxSteps: 4,
};

describe('reproducible, source-constrained scenario propagation', () => {
  it('produces identical values for a fixed data version, inputs and seed', () => {
    const a = simulateScenario(scenario, network);
    const b = simulateScenario(scenario, network);
    expect(a).toEqual(b);
  });

  it('does not invent exposure where no source node or edge is present', () => {
    const result = simulateScenario(scenario, network);
    expect(result.industries.some((row) => row.country === 'CCC')).toBe(false);
    expect(result.industries.some((row) => row.country === 'ROW')).toBe(false);
    expect(result.industries.find((row) => row.nodeId === 'JPN_C29')?.step).toBe(2);
  });

  it('applies substitution and inventory only to downstream transmission', () => {
    const resilient = simulateScenario({ ...scenario, substitution: { min: 1, max: 1 }, inventory: { min: 1, max: 1 } }, network);
    expect(resilient.industries.map((row) => row.nodeId)).toEqual(['AAA_C26']);
    expect(resilient.industries[0]?.p50).toBeGreaterThan(0);
  });

  it('does not count parallel unobserved finance/capital links as a procurement edge', () => {
    // The engine accepts only explicit IO flows and seed nodes; corporate relations are not an input.
    const noFlowNetwork: FlowNetwork = { ...network, edges: [] };
    expect(simulateScenario(scenario, noFlowNetwork).industries).toHaveLength(1);
  });

  it('reports first downstream industry separately from an imposed source condition', () => {
    const result = simulateScenario(scenario, network);
    expect(result.industries[0]?.nodeId).toBe('AAA_C26');
    expect(result.summary.affectedIndustryCount).toBe(2);
    expect(result.countries.every((country) => country.country !== 'AAA')).toBe(true);
    expect(result.countries.some((country) => country.country === 'JPN' && country.step === 2)).toBe(true);
  });

  it('does not let a seed in the same country contaminate downstream country step and coverage counts', () => {
    const countryNodes = [
      ...nodes,
      { id: 'AAA_C19', country: 'AAA', industry: 'C19', industryJa: '石油・石炭製品', isRow: false, isFinalDemand: false },
    ];
    const sameCountryNetwork: FlowNetwork = {
      nodes: countryNodes,
      edges: [...network.edges, { seller: 0, buyer: 4, coefficient: 0.5 }],
      nodeIndex: new Map(countryNodes.map((node, index) => [node.id, index])),
    };
    const result = simulateScenario(scenario, sameCountryNetwork);
    const sourceCountry = result.countries.find((country) => country.country === 'AAA');
    expect(sourceCountry?.step).toBe(1);
    expect(sourceCountry?.coveredIndustries).toBe(1);
  });

  it('rejects duplicate buyer-seller flow cells instead of double counting them', () => {
    const duplicate: FlowNetwork = { ...network, edges: [...network.edges, network.edges[0]] };
    expect(() => simulateScenario(scenario, duplicate)).toThrow(/Duplicate ICIO buyer-seller flow/);
  });

  it('treats final-demand-only columns as terminal sinks, not exposed production industries', () => {
    const finalDemandNodes: IndustryNode[] = [
      ...nodes,
      { id: 'AAA_INVNT', country: 'AAA', industry: 'INVNT', industryJa: '在庫変動', isRow: false, isFinalDemand: true },
    ];
    const finalDemandNetwork: FlowNetwork = {
      nodes: finalDemandNodes,
      edges: [...network.edges, { seller: 0, buyer: 4, coefficient: 25.6 }],
      nodeIndex: new Map(finalDemandNodes.map((node, index) => [node.id, index])),
    };
    const result = simulateScenario(scenario, finalDemandNetwork);
    expect(result.industries.some((row) => row.nodeId === 'AAA_INVNT')).toBe(false);
    expect(result.summary.affectedIndustryCount).toBe(2);
    expect(() => simulateScenario({ ...scenario, seedNodes: ['AAA_INVNT'] }, finalDemandNetwork)).toThrow(/terminal-demand node/);
  });

  it('shows a conditional sensitivity range, not an event probability', () => {
    const result = simulateScenario(scenario, network);
    expect(result.summary.distributionLabel).toContain('事象発生確率');
    for (const row of result.industries) {
      expect(row.p10).toBeLessThanOrEqual(row.p50);
      expect(row.p50).toBeLessThanOrEqual(row.p90);
    }
  });

  it('refuses missing nodes and impossible numeric ranges rather than substituting a guess', () => {
    expect(() => simulateScenario({ ...scenario, seedNodes: ['MISSING_C20'] }, network)).toThrow(/not in the selected ICIO snapshot/);
    expect(() => simulateScenario({ ...scenario, shock: { min: 1.2, max: 1.4 } }, network)).toThrow(/shock/);
  });
});
