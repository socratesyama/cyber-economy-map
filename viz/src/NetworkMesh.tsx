import { useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react';
import { ArrowUpRight, Maximize2, Minus, Plus, Search } from 'lucide-react';
import type { FirmRecord, IndustryImpact, OwnershipLayoutPoint, OwnershipRecord } from './engine/types';

interface Props {
  companies: FirmRecord[];
  layout: OwnershipLayoutPoint[];
  ownership: OwnershipRecord[];
  impacts: IndustryImpact[];
}

interface ScreenPoint { id: string; x: number; y: number; }
interface OwnershipGroup {
  srcId: string;
  dstId: string;
  evidence: OwnershipRecord[];
  visualStatus: string;
}
const NO_IMPACTS: IndustryImpact[] = [];
const pairKey = (source: string, target: string) => `${source}\u001f${target}`;
const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(value, max));

function interpolateShock(value: number, max: number): string {
  const t = clamp(value / Math.max(max, 1e-9), 0, 1);
  const start = [218, 196, 175];
  const end = [180, 77, 60];
  return `rgb(${start.map((base, index) => Math.round(base + (end[index] - base) * t)).join(',')})`;
}

function statusLabel(status: string): string {
  if (status === 'observed_value') return '比率の観測';
  if (status === 'observed_binary') return '関係の観測';
  if (status === 'estimated') return '推定関係';
  if (status === 'multiple') return '複数記録・要確認';
  return `状態: ${status}`;
}

function statusClass(status: string): string {
  if (status === 'estimated') return 'estimated';
  if (status === 'multiple' || status === 'unknown') return 'mixed';
  return 'observed';
}

export function NetworkMesh({ companies, layout, ownership, impacts = NO_IMPACTS }: Props) {
  const [search, setSearch] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [centerOnSelection, setCenterOnSelection] = useState(false);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const screenPointsRef = useRef<ScreenPoint[]>([]);

  const positionById = useMemo(() => new Map(layout.map((point) => [point.id, point])), [layout]);
  const visibleCompanies = useMemo(
    () => companies.filter((company) => positionById.has(company.id)),
    [companies, positionById],
  );
  const visibleEdges = useMemo(() => {
    const grouped = new Map<string, OwnershipRecord[]>();
    for (const record of ownership) {
      if (!positionById.has(record.src_id) || !positionById.has(record.dst_id)) continue;
      const key = pairKey(record.src_id, record.dst_id);
      const existing = grouped.get(key);
      if (existing) existing.push(record);
      else grouped.set(key, [record]);
    }
    return [...grouped.values()].map((evidence): OwnershipGroup => {
      const statuses = new Set(evidence.map((record) => record.dependency_status));
      return {
        srcId: evidence[0].src_id,
        dstId: evidence[0].dst_id,
        evidence,
        visualStatus: statuses.size === 1 ? evidence[0].dependency_status : 'multiple',
      };
    });
  }, [ownership, positionById]);
  const companyById = useMemo(() => new Map(companies.map((company) => [company.id, company])), [companies]);
  const downstreamImpact = useMemo(
    () => new Map(impacts.filter((impact) => impact.country === 'JPN' && impact.step > 0)
      .map((impact) => [impact.nodeId, impact.p50])),
    [impacts],
  );
  const maxImpact = useMemo(() => Math.max(0.0001, ...downstreamImpact.values()), [downstreamImpact]);
  const relatedEdges = useMemo(() => selectedId
    ? visibleEdges.filter((edge) => edge.srcId === selectedId || edge.dstId === selectedId)
    : [], [selectedId, visibleEdges]);
  const neighborIds = useMemo(() => new Set(relatedEdges.map((edge) => edge.srcId === selectedId ? edge.dstId : edge.srcId)), [relatedEdges, selectedId]);
  const selectedCompany = selectedId ? companyById.get(selectedId) ?? null : null;
  const totalUniquePairs = useMemo(
    () => new Set(ownership.map((edge) => pairKey(edge.src_id, edge.dst_id))).size,
    [ownership],
  );
  const visibleEvidenceRecords = visibleEdges.reduce((total, group) => total + group.evidence.length, 0);
  const omittedPairs = totalUniquePairs - visibleEdges.length;
  const omittedRecords = ownership.length - visibleEvidenceRecords;

  const query = search.trim().toLocaleLowerCase('ja-JP');
  const matches = useMemo(() => {
    if (!query) return [];
    return visibleCompanies.filter((company) => [company.name, company.ticker ?? '', company.sector ?? '']
      .some((value) => value.toLocaleLowerCase('ja-JP').includes(query))).slice(0, 6);
  }, [query, visibleCompanies]);

  useEffect(() => {
    const element = frameRef.current;
    if (!element) return;
    const measure = () => {
      const rect = element.getBoundingClientRect();
      setSize((current) => current.width === rect.width && current.height === rect.height
        ? current : { width: rect.width, height: rect.height });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || size.width < 1 || size.height < 1 || !layout.length) return;
    const ratio = Math.max(1, window.devicePixelRatio || 1);
    canvas.width = Math.round(size.width * ratio);
    canvas.height = Math.round(size.height * ratio);
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.fillStyle = '#fbfaf6';
    ctx.fillRect(0, 0, size.width, size.height);

    const bounds = layout.reduce((box, point) => ({
      minX: Math.min(box.minX, point.x), maxX: Math.max(box.maxX, point.x),
      minY: Math.min(box.minY, point.y), maxY: Math.max(box.maxY, point.y),
    }), { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity });
    const extentX = Math.max(1e-6, bounds.maxX - bounds.minX);
    const extentY = Math.max(1e-6, bounds.maxY - bounds.minY);
    const fit = Math.min(Math.max(1, size.width - 32) / extentX, Math.max(1, size.height - 28) / extentY);
    const activeFocus = centerOnSelection && selectedId ? positionById.get(selectedId) : undefined;
    const centerX = activeFocus?.x ?? (bounds.minX + bounds.maxX) / 2;
    const centerY = activeFocus?.y ?? (bounds.minY + bounds.maxY) / 2;
    const scale = Math.max(0.01, fit) * zoom;
    const toScreen = (point: OwnershipLayoutPoint) => ({
      x: size.width / 2 + (point.x - centerX) * scale,
      y: size.height / 2 + (point.y - centerY) * scale,
    });
    const screenPoints = layout.map((point) => ({ id: point.id, ...toScreen(point) }));
    screenPointsRef.current = screenPoints;
    const screenById = new Map(screenPoints.map((point) => [point.id, point]));

    const drawEdge = (group: OwnershipGroup, active: boolean) => {
      const from = screenById.get(group.srcId);
      const to = screenById.get(group.dstId);
      if (!from || !to) return;
      ctx.beginPath();
      ctx.moveTo(from.x, from.y);
      ctx.lineTo(to.x, to.y);
      ctx.setLineDash(['estimated', 'multiple', 'unknown'].includes(group.visualStatus) ? [3, 2] : []);
      ctx.lineWidth = active ? 1.6 : 0.55;
      ctx.strokeStyle = active ? (group.visualStatus === 'estimated' ? '#916016' : '#B44D3C') : '#657c89';
      ctx.globalAlpha = active ? 0.95 : (selectedId ? 0.09 : 0.3);
      ctx.stroke();
    };
    for (const group of visibleEdges) {
      const active = Boolean(selectedId && (group.srcId === selectedId || group.dstId === selectedId));
      if (!active) drawEdge(group, false);
    }
    if (selectedId) for (const group of relatedEdges) drawEdge(group, true);
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;

    for (const firm of visibleCompanies) {
      const point = screenById.get(firm.id);
      if (!point || point.x < -8 || point.x > size.width + 8 || point.y < -8 || point.y > size.height + 8) continue;
      const isSelected = firm.id === selectedId;
      const isNeighbor = neighborIds.has(firm.id);
      const impact = firm.industryNode ? downstreamImpact.get(firm.industryNode) : undefined;
      const fill = isSelected ? '#B44D3C' : isNeighbor ? '#c38b3e'
        : impact !== undefined ? interpolateShock(impact, maxImpact)
          : impacts.length ? '#c5cbc7' : '#315f78';
      ctx.beginPath();
      ctx.arc(point.x, point.y, isSelected ? 5.8 : isNeighbor ? 3.8 : 2.25, 0, Math.PI * 2);
      ctx.fillStyle = fill;
      ctx.fill();
      if (isSelected) {
        ctx.beginPath();
        ctx.arc(point.x, point.y, 9, 0, Math.PI * 2);
        ctx.strokeStyle = '#B44D3C';
        ctx.lineWidth = 1.2;
        ctx.stroke();
      }
    }
  }, [centerOnSelection, downstreamImpact, impacts.length, layout, maxImpact, neighborIds, positionById, relatedEdges, selectedId, size, visibleCompanies, visibleEdges, zoom]);

  const focusCompany = (id: string) => {
    setSelectedId(id);
    setSearch('');
    setCenterOnSelection(true);
    setZoom((value) => Math.max(value, 1.8));
  };
  const selectFromCanvas = (event: ReactMouseEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    let nearest: ScreenPoint | null = null;
    let minimum = 11;
    for (const point of screenPointsRef.current) {
      const distance = Math.hypot(point.x - x, point.y - y);
      if (distance < minimum) { minimum = distance; nearest = point; }
    }
    if (nearest) focusCompany(nearest.id);
  };

  return (
    <div className="ownership-mesh" role="region" aria-label="日本上場企業の資本関係ネットワーク">
      <div className="mesh-toolbar">
        <div className="mesh-search-wrap">
          <label className="mesh-search-label" htmlFor="mesh-company-search"><Search size={15} aria-hidden="true" /> 企業を検索</label>
          <input id="mesh-company-search" type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="会社名・銘柄コード・業種" aria-describedby="mesh-search-help" />
          <span id="mesh-search-help" className="mesh-search-help">検索結果を選ぶと、その企業を中心に表示します。</span>
          {query && <ul className="mesh-search-results" aria-label="企業検索結果">
            {matches.map((firm) => <li key={firm.id}><button type="button" onClick={() => focusCompany(firm.id)}><b>{firm.name}</b><span>{firm.ticker ?? firm.id} · {firm.sector ?? '業種分類なし'}</span></button></li>)}
            {matches.length === 0 && <li className="mesh-search-empty">一致する配置済み企業がありません</li>}
          </ul>}
        </div>
        <div className="mesh-view-controls" aria-label="ネットワーク表示倍率">
          <button type="button" aria-label="縮小" onClick={() => setZoom((value) => clamp(value / 1.35, 0.65, 8))}><Minus size={15} /></button>
          <span>{Math.round(zoom * 100)}%</span>
          <button type="button" aria-label="拡大" onClick={() => setZoom((value) => clamp(value * 1.35, 0.65, 8))}><Plus size={15} /></button>
          <button type="button" className="mesh-fit-button" onClick={() => { setZoom(1); setCenterOnSelection(false); }}><Maximize2 size={14} /><span>全体表示</span></button>
        </div>
      </div>

      <div className="mesh-countline" aria-live="polite" aria-atomic="true">
        <span><b>{visibleCompanies.length.toLocaleString('ja-JP')}</b> 配置ノード</span>
        <span><b>{visibleEdges.length.toLocaleString('ja-JP')}</b> 描画する一意ペア</span>
        <span>{ownership.length.toLocaleString('ja-JP')} 関係記録 · {totalUniquePairs.toLocaleString('ja-JP')} 一意ペア</span>
        <span className="mesh-projection-tag">既存3D配置のPCA投影 · 地理座標ではない</span>
      </div>
      <p className="mesh-boundary-note"><b>表示範囲：</b>{ownership.length.toLocaleString('ja-JP')}件の関係記録は{totalUniquePairs.toLocaleString('ja-JP')}組の一意ペアです。双方が{visibleCompanies.length.toLocaleString('ja-JP')}社の配置内にある{visibleEdges.length.toLocaleString('ja-JP')}組だけを描画し、配置外端点のある{omittedPairs.toLocaleString('ja-JP')}組（{omittedRecords.toLocaleString('ja-JP')}件）は架空の位置を作らず非表示にしています。同じペアの複数記録は線を重ねず、企業を選ぶと根拠記録を確認できます。</p>

      <div className="mesh-canvas-wrap" ref={frameRef}>
        <canvas ref={canvasRef} className="ownership-canvas" aria-hidden="true" onClick={selectFromCanvas} />
        <span className="mesh-canvas-hint" aria-hidden="true">点を選択して関係を表示。会社名検索も利用できます</span>
      </div>

      <div className="mesh-legend" aria-label="メッシュの凡例">
        <span><i className="mesh-legend__node" />企業</span>
        <span><i className="mesh-legend__line" />記録済み資本関係</span>
        <span><i className="mesh-legend__line mesh-legend__line--estimated" />推定・複数状態</span>
        <span><i className="mesh-legend__node mesh-legend__node--selected" />選択企業</span>
        {impacts.length > 0 && <span><i className="mesh-legend__scale" />色は国×産業の業種代理</span>}
      </div>

      {selectedCompany ? (
        <aside className="mesh-detail" aria-live="polite" aria-atomic="true">
          <div className="mesh-detail__header"><div><span className="eyebrow">SELECTED COMPANY / OWNERSHIP ONLY</span><h3>{selectedCompany.name}</h3><p>{selectedCompany.ticker ?? selectedCompany.id} · {selectedCompany.sector ?? '業種分類なし'}</p></div><span className="count-badge">{relatedEdges.length} 組</span></div>
          {selectedCompany.industryNode && downstreamImpact.has(selectedCompany.industryNode) && (
            <div className="mesh-proxy"><b>業種代理 · {Math.round((downstreamImpact.get(selectedCompany.industryNode) ?? 0) * 1000) / 10}%</b><span>対応する国×産業IO指標です。企業固有の損失・供給依存ではありません。</span></div>
          )}
          {relatedEdges.length === 0 ? <p className="mesh-empty">この企業に接続する資本関係は、この描画範囲に記録されていません。</p> : (
            <ul className="mesh-relations">
              {relatedEdges.slice(0, 8).map((group) => {
                const counterpart = group.srcId === selectedCompany.id ? group.dstId : group.srcId;
                const firm = companyById.get(counterpart);
                const direction = group.srcId === selectedCompany.id ? '関係先 / 下位' : '親・出資元';
                const statusText = new Set(group.evidence.map((record) => record.dependency_status)).size > 1
                  ? 'multiple' : group.visualStatus;
                return <li key={pairKey(group.srcId, group.dstId)}>
                  <span className={`mesh-status mesh-status--${statusClass(statusText)}`}>{statusLabel(statusText)}</span>
                  <span className="mesh-relation__label">
                    <b>{firm?.name ?? `境界ノード ${counterpart}`}</b>
                    <small>{direction} · {group.evidence[0].relation_type} · {group.evidence.length}件の根拠記録</small>
                    <details className="mesh-evidence">
                      <summary>出典・時点・比率を確認</summary>
                      <ul>{group.evidence.map((record) => <li key={record.edge_id}>
                        <span>{statusLabel(record.dependency_status)} · {record.as_of || '時点記録なし'}{record.share_pct !== null ? ` · ${Number(record.share_pct).toFixed(1)}%` : ''} · source tier {record.source_tier}</span>
                        {record.source_ref?.startsWith('http') ? <a href={record.source_ref} target="_blank" rel="noreferrer">原典を開く <ArrowUpRight size={12} /></a> : <span>原典リンクなし</span>}
                      </li>)}</ul>
                    </details>
                  </span>
                  {firm && <button type="button" className="mesh-related-select" onClick={() => focusCompany(counterpart)} aria-label={`${firm.name}をメッシュの中心に表示`}>表示</button>}
                </li>;
              })}
            </ul>
          )}
          {relatedEdges.length > 8 && <p className="mesh-search-help">他 {relatedEdges.length - 8} 組の関係は検索して選択できます。</p>}
          <p className="mesh-evidence-caveat">ここにあるのは資本関係の記録です。売上・仕入依存や企業固有損失を表しません。関係が表示されないことも、関係がない証明ではありません。</p>
        </aside>
      ) : <p className="mesh-empty">検索または点を選択すると、表示範囲内の資本関係とすべての根拠記録を確認できます。範囲外リンクは配置せず、資本リンクを通じたショック伝播も計算していません。</p>}
    </div>
  );
}
