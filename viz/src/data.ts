import type { FeatureCollection, Geometry } from 'geojson';
import type { DataManifest, FirmRecord, IndustryNode, OwnershipRecord } from './engine/types';

export interface PortRecord {
  port_id: string;
  name: string;
  country: string;
  lat: number;
  lon: number;
  teu_annual: number | null;
  source: string;
}

export interface CountryProperties {
  iso3: string;
  name: string;
  nameJa: string;
  boundaryBasis: string;
}

export interface Snapshot {
  manifest: DataManifest;
  industries: IndustryNode[];
  companies: FirmRecord[];
  ownership: OwnershipRecord[];
  ports: PortRecord[];
  world: FeatureCollection<Geometry, CountryProperties>;
}

const dataUrl = (file: string) => `/data/${file}`;

async function readJson<T>(file: string): Promise<T> {
  const response = await fetch(dataUrl(file), { headers: { accept: 'application/json' } });
  if (!response.ok) throw new Error(`Data snapshot ${file} could not be read (HTTP ${response.status}).`);
  return response.json() as Promise<T>;
}

export async function loadSnapshot(): Promise<Snapshot> {
  const [manifest, industries, companies, ownership, ports, world] = await Promise.all([
    readJson<DataManifest>('manifest.json'),
    readJson<IndustryNode[]>('industries.json'),
    readJson<FirmRecord[]>('companies.json'),
    readJson<OwnershipRecord[]>('ownership.json'),
    readJson<PortRecord[]>('ports.json'),
    readJson<FeatureCollection<Geometry, CountryProperties>>('world.geojson'),
  ]);
  return { manifest, industries, companies, ownership, ports, world };
}

export async function readFlowSnapshot(): Promise<ArrayBuffer> {
  const response = await fetch(dataUrl('icio2020-flows.bin'));
  if (!response.ok) throw new Error(`ICIO snapshot could not be read (HTTP ${response.status}).`);
  return response.arrayBuffer();
}
