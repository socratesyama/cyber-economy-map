import type {
  CountryImpact,
  FlowNetwork,
  IndustryImpact,
  ScenarioInput,
  ScenarioResult,
} from './types';

function boundedRange(label: string, value: { min: number; max: number }, upper: number): void {
  if (!Number.isFinite(value.min) || !Number.isFinite(value.max) || value.min < 0 || value.max < value.min || value.max > upper) {
    throw new RangeError(`${label} must satisfy 0 <= min <= max <= ${upper}`);
  }
}

/** Fixed integer PRNG. Every sensitivity draw is repeatable, not an event probability. */
function seededRandom(seed: number): () => number {
  let state = seed >>> 0;
  if (state === 0) state = 0x6d2b79f5;
  return () => {
    state += 0x6d2b79f5;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

function quantile(values: number[], fraction: number): number {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const position = (sorted.length - 1) * fraction;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  const mix = position - lower;
  return sorted[lower] * (1 - mix) + sorted[upper] * mix;
}

function draw(range: { min: number; max: number }, random: () => number): number {
  return range.min + (range.max - range.min) * random();
}

export function simulateScenario(
  scenario: ScenarioInput,
  network: FlowNetwork,
  onProgress?: (completed: number, total: number) => void,
): ScenarioResult {
  boundedRange('shock', scenario.shock, scenario.channel === 'input-cost' ? 10 : 1);
  boundedRange('substitution', scenario.substitution, 1);
  boundedRange('inventory', scenario.inventory, 1);
  boundedRange('passThrough', scenario.passThrough, 1);
  if (scenario.seedNodes.length === 0) throw new Error('Select at least one sourced country-industry node.');
  if (!Number.isInteger(scenario.samples) || scenario.samples < 3 || scenario.samples > 400) {
    throw new RangeError('Sensitivity sample count must be between 3 and 400.');
  }
  if (!Number.isInteger(scenario.maxSteps) || scenario.maxSteps < 1 || scenario.maxSteps > 12) {
    throw new RangeError('Propagation steps must be between 1 and 12.');
  }

  const seedIndexes = scenario.seedNodes.map((nodeId) => {
    const id = network.nodeIndex.get(nodeId);
    if (id === undefined) throw new Error(`The source node ${nodeId} is not in the selected ICIO snapshot.`);
    if (network.nodes[id].isRow || network.nodes[id].isFinalDemand) {
      throw new Error(`The source node ${nodeId} is a non-production or terminal-demand node, not a modelled production industry.`);
    }
    return id;
  });
  const uniqueFlows = new Set<string>();
  for (const edge of network.edges) {
    if (!Number.isInteger(edge.buyer) || !Number.isInteger(edge.seller) || edge.buyer < 0 || edge.seller < 0
        || edge.buyer >= network.nodes.length || edge.seller >= network.nodes.length
        || !Number.isFinite(edge.coefficient) || edge.coefficient < 0) {
      throw new Error('The ICIO network contains an invalid buyer-seller flow.');
    }
    const key = `${edge.buyer}:${edge.seller}`;
    if (uniqueFlows.has(key)) throw new Error(`Duplicate ICIO buyer-seller flow ${key}; refusing to double-count it.`);
    uniqueFlows.add(key);
  }
  const sampleValues = network.nodes.map(() => [] as number[]);
  const firstSteps = new Uint8Array(network.nodes.length);
  const random = seededRandom(scenario.seed);

  for (let sample = 0; sample < scenario.samples; sample += 1) {
    const loss = new Float64Array(network.nodes.length);
    let frontier = new Float64Array(network.nodes.length);
    const amount = draw(scenario.shock, random);
    const substitution = draw(scenario.substitution, random);
    const inventory = draw(scenario.inventory, random);
    const passThrough = draw(scenario.passThrough, random);

    // Multiple shocks on the same measured sector are not added into duplicate flow losses.
    // Keep the largest explicitly specified source condition per node for this run.
    for (const id of seedIndexes) {
      if (amount > frontier[id]) {
        frontier[id] = amount;
        loss[id] = amount;
        if (firstSteps[id] === 0) firstSteps[id] = 1;
      }
    }

    for (let step = 1; step <= scenario.maxSteps; step += 1) {
      const incoming = new Float64Array(network.nodes.length);
      let any = false;
      const mitigation = scenario.channel === 'production-outage'
        ? (1 - substitution) * (1 - inventory)
        : passThrough;
      for (const edge of network.edges) {
        const upstream = frontier[edge.seller];
        if (upstream <= 0) continue;
        const amountToBuyer = edge.coefficient * upstream * mitigation;
        if (amountToBuyer <= 1e-9) continue;
        // Every buyer-seller coefficient is one distinct sectoral flow cell.
        incoming[edge.buyer] += amountToBuyer;
        any = true;
      }
      if (!any) break;

      const next = new Float64Array(network.nodes.length);
      for (let nodeId = 0; nodeId < incoming.length; nodeId += 1) {
        const add = Math.min(1, incoming[nodeId]) * Math.max(0, 1 - loss[nodeId]);
        if (add <= 1e-9) continue;
        loss[nodeId] = Math.min(1, loss[nodeId] + add);
        next[nodeId] = add;
        if (firstSteps[nodeId] === 0) firstSteps[nodeId] = Math.min(255, step + 1);
      }
      frontier = next;
      onProgress?.(sample * scenario.maxSteps + step, scenario.samples * scenario.maxSteps);
    }
    for (let nodeId = 0; nodeId < loss.length; nodeId += 1) sampleValues[nodeId].push(loss[nodeId]);
    if (scenario.maxSteps === 0) onProgress?.(sample + 1, scenario.samples);
  }

  const impacts: IndustryImpact[] = [];
  const countrySamples = new Map<string, number[][]>();
  for (let i = 0; i < network.nodes.length; i += 1) {
    const node = network.nodes[i];
    if (node.isRow || node.country === 'ROW' || node.isFinalDemand) continue;
    const values = sampleValues[i];
    const p50 = quantile(values, 0.5);
    const p10 = quantile(values, 0.1);
    const p90 = quantile(values, 0.9);
    if (p90 <= 1e-5) continue;
    const step = firstSteps[i] === 0 ? scenario.maxSteps + 1 : Math.max(0, firstSteps[i] - 1);
    impacts.push({
      nodeId: node.id, country: node.country, industry: node.industry,
      industryJa: node.industryJa, step, p10, p50, p90,
    });
    // The seed describes the imposed condition, not a ripple onto that country's other buyers.
    // Keep it in the full replay bundle, but do not let it dominate the downstream map.
    if (step > 0) {
      const aggregate = countrySamples.get(node.country) ?? Array.from({ length: scenario.samples }, () => []);
      values.forEach((value, sample) => aggregate[sample].push(value));
      countrySamples.set(node.country, aggregate);
    }
  }
  impacts.sort((a, b) => a.step - b.step || b.p50 - a.p50 || a.country.localeCompare(b.country));

  const countries: CountryImpact[] = [];
  for (const [country, samples] of countrySamples) {
    const eachSample = samples.map((values) => values.reduce((sum, value) => sum + value, 0) / Math.max(values.length, 1));
    const detail = impacts.filter((row) => row.country === country && row.step > 0);
    countries.push({
      country, p10: quantile(eachSample, 0.1), p50: quantile(eachSample, 0.5),
      p90: quantile(eachSample, 0.9), coveredIndustries: detail.length,
      step: Math.min(...detail.map((row) => row.step)),
    });
  }
  countries.sort((a, b) => b.p50 - a.p50 || a.country.localeCompare(b.country));

  return {
    input: structuredClone(scenario),
    summary: {
      samples: scenario.samples, maxPropagationSteps: scenario.maxSteps,
      channel: scenario.channel,
      distributionLabel: '感度レンジ内の一様入力スイープによる条件付きP10/P50/P90。事象発生確率・実証済み予測区間ではありません。',
      affectedIndustryCount: impacts.filter((impact) => impact.step > 0).length,
    },
    industries: impacts,
    countries,
  };
}
