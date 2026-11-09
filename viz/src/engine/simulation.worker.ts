import { simulateScenario } from './simulate';
import type { FlowNetwork, IndustryNode, ScenarioInput, ScenarioResult } from './types';

interface WorkerJob {
  type: 'simulate';
  scenario: ScenarioInput;
  nodes: IndustryNode[];
  flowsBuffer: ArrayBuffer;
}

interface WorkerProgress {
  type: 'progress';
  completed: number;
  total: number;
}

interface WorkerSuccess {
  type: 'result';
  result: ScenarioResult;
}

interface WorkerFailure {
  type: 'error';
  message: string;
}

declare const self: DedicatedWorkerGlobalScope;

self.addEventListener('message', (event: MessageEvent<WorkerJob>) => {
  const { scenario, nodes, flowsBuffer } = event.data;
  try {
    const view = new DataView(flowsBuffer);
    const edges = [];
    const recordBytes = 8;
    if (flowsBuffer.byteLength % recordBytes !== 0) throw new Error('The ICIO binary snapshot is truncated.');
    for (let offset = 0; offset < flowsBuffer.byteLength; offset += recordBytes) {
      const buyer = view.getUint16(offset, true);
      const seller = view.getUint16(offset + 2, true);
      const coefficient = view.getFloat32(offset + 4, true);
      if (buyer >= nodes.length || seller >= nodes.length || !Number.isFinite(coefficient) || coefficient < 0) {
        throw new Error('Invalid buyer/seller index or coefficient in ICIO snapshot.');
      }
      edges.push({ buyer, seller, coefficient });
    }
    const network: FlowNetwork = {
      nodes,
      edges,
      nodeIndex: new Map(nodes.map((node, id) => [node.id, id])),
    };
    const result = simulateScenario(scenario, network, (completed, total) => {
      if (completed % 4 === 0 || completed === total) {
        const message: WorkerProgress = { type: 'progress', completed, total };
        self.postMessage(message);
      }
    });
    const response: WorkerSuccess = { type: 'result', result };
    self.postMessage(response);
  } catch (error) {
    const response: WorkerFailure = { type: 'error', message: error instanceof Error ? error.message : 'Scenario could not be computed.' };
    self.postMessage(response);
  }
});
