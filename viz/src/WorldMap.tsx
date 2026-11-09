import { useMemo } from 'react';
import { geoEqualEarth, geoPath } from 'd3-geo';
import type { FeatureCollection, Geometry } from 'geojson';
import type { CountryProperties } from './data';
import type { CountryImpact } from './engine/types';
import type { PortRecord } from './data';

interface Props {
  world: FeatureCollection<Geometry, CountryProperties>;
  impacts: CountryImpact[];
  ports: PortRecord[];
  selectedCountry: string | null;
  onSelectCountry: (iso3: string) => void;
}

const W = 900;
const H = 445;

function color(value: number | undefined, maximum: number): string {
  if (value === undefined || value <= 0.00001) return '#e7e8e2';
  const ratio = Math.max(0, Math.min(value / Math.max(maximum, 1e-7), 1));
  const low = [231, 209, 187];
  const high = [174, 59, 44];
  const t = Math.pow(ratio, 0.56);
  return `rgb(${low.map((x, i) => Math.round(x + (high[i] - x) * t)).join(',')})`;
}

export function WorldMap({ world, impacts, ports, selectedCountry, onSelectCountry }: Props) {
  const projection = useMemo(() => geoEqualEarth().fitExtent([[18, 12], [W - 18, H - 18]], world), [world]);
  const path = useMemo(() => geoPath(projection), [projection]);
  const byCountry = new Map(impacts.map((item) => [item.country, item]));
  const maximum = Math.max(...impacts.map((item) => item.p90), 0.00001);

  return (
    <div className="map-scroll" role="region" aria-label="国境地図。影響候補国は選択して結果を確認できます。色はカバー済み国産業の平均条件付きIO影響指標で、港湾露出や航路は表しません。">
      <svg className="world-map" viewBox={`0 0 ${W} ${H}`} aria-labelledby="map-title map-description">
        <title id="map-title">世界の国×産業における条件付き影響</title>
        <desc id="map-description">Natural Earth 1対1億1千万国境データを基図とし、色はICIO係数から計算した条件付き感度結果を示します。白黒や低色はデータが無いという意味ではなく、その分類に有効ノードが無い国は個別に表示します。航路線はありません。</desc>
        {world.features.map((feature, index) => {
          const country = feature.properties.iso3;
          const impact = byCountry.get(country);
          const selected = country === selectedCountry;
          const d = path(feature) ?? '';
          if (!d) return null;
          const label = feature.properties.nameJa || feature.properties.name || country;
          return (
            <path
              key={`${country}-${index}`}
              d={d}
              fill={color(impact?.p50, maximum)}
              stroke={selected ? '#172536' : '#bac2c0'}
              strokeWidth={selected ? 1.6 : 0.55}
              vectorEffect="non-scaling-stroke"
              className={impact ? 'map-country map-country--impacted' : 'map-country'}
              role={impact ? 'button' : undefined}
              tabIndex={impact && country ? 0 : -1}
              aria-label={impact ? `${label} ${country}, 感度中央値 ${(impact.p50 * 100).toFixed(1)}パーセント, ${impact.coveredIndustries}業種をカバー` : undefined}
              aria-pressed={impact ? selected : undefined}
              onClick={() => impact && country && onSelectCountry(country)}
              onKeyDown={(event) => {
                if (impact && country && (event.key === 'Enter' || event.key === ' ')) {
                  event.preventDefault();
                  onSelectCountry(country);
                }
              }}
            >
              <title>{`${label} (${country})${impact ? ` · 条件付き国産業平均 ${(impact.p50 * 100).toFixed(2)}%` : ' · この実行では該当結果なしまたは国産業未カバー'}`}</title>
            </path>
          );
        })}
        {ports.map((port) => {
          const [x, y] = projection([port.lon, port.lat]) ?? [0, 0];
          return (
            <g key={port.port_id} className="port-marker" aria-hidden="true">
              <circle cx={x} cy={y} r={4.2} />
              <circle cx={x} cy={y} r={7.2} className="port-marker__halo" />
              <title>{`${port.name} · 実測座標。企業・産業の利用リンクは未収録。`}</title>
            </g>
          );
        })}
      </svg>
      <div className="map-scale" aria-label="地図の凡例">
        <span>低</span><i className="map-scale__gradient" /><span>高</span>
        <span className="map-scale__unit">条件付きIO感度（%）</span>
      </div>
    </div>
  );
}
