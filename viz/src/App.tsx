import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Activity, ArrowRight, ArrowUpRight, BookOpen, Building2, Check, ChevronDown,
  CircleAlert, Clipboard, Database, Download, FileJson2, GitBranch, Globe2, Info,
  Layers3, Orbit, Play, ShieldAlert, Sparkles, Table2,
} from 'lucide-react';
import { CompanyDirectory } from './CompanyDirectory';
import { loadSnapshot, readFlowSnapshot, type Snapshot } from './data';
import { DEFAULT_EVENT_ID, EVENTS } from './events';
import type { FirmRecord, IndustryImpact, ScenarioBundle, ScenarioInput, ScenarioResult } from './engine/types';
import { WorldMap } from './WorldMap';
import { RippleGlyph } from './RippleGlyph';

const MODEL_VERSION = '0.1.0';
const ENERGY_SECTORS = new Set(['B05_06']);
const NAV = [
  { id: 'atlas', label: 'シナリオ分析', icon: Globe2 },
  { id: 'companies', label: '企業名鑑', icon: Building2 },
  { id: 'data', label: 'データ・方法', icon: Database },
  { id: 'events', label: '事象カタログ', icon: Layers3 },
] as const;
type Page = (typeof NAV)[number]['id'];
interface SavedRun { key: string; title: string; when: string; input: ScenarioInput; top: Array<Pick<IndustryImpact, 'nodeId' | 'country' | 'industryJa' | 'p50'>>; }
const percent = (value: number) => `${(value * 100).toFixed(1)}%`;

function saveBlob(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

function Slot({ children }: { children: ReactNode }) { return <span className="eyebrow">{children}</span>; }

function RangePair({
  label, low, high, onLow, onHigh, unit = '%', disabled = false,
}: {
  label: string; low: string; high: string; onLow: (v: string) => void; onHigh: (v: string) => void;
  unit?: string; disabled?: boolean;
}) {
  return (
    <fieldset className="range-pair" disabled={disabled}>
      <legend>{label}</legend>
      <label><span>下限</span><input type="number" value={low} onChange={(event) => onLow(event.target.value)} min="0" max="100" step="1" aria-label={`${label}の下限`} /><small>{unit}</small></label>
      <span className="range-pair__to">—</span>
      <label><span>上限</span><input type="number" value={high} onChange={(event) => onHigh(event.target.value)} min="0" max="100" step="1" aria-label={`${label}の上限`} /><small>{unit}</small></label>
    </fieldset>
  );
}

function buildScenario({
  eventId, snapshot, country, industry, manualAccepted, shockLow, shockHigh, subLow, subHigh, bufferLow, bufferHigh, passLow, passHigh,
}: {
  eventId: string; snapshot: Snapshot | null; country: string; industry: string; manualAccepted: boolean;
  shockLow: string; shockHigh: string; subLow: string; subHigh: string; bufferLow: string; bufferHigh: string; passLow: string; passHigh: string;
}): ScenarioInput | null {
  if (!snapshot) return null;
  const event = EVENTS.find((candidate) => candidate.id === eventId) ?? EVENTS[0];
  const seed = event.id === 'oil-x2'
    ? snapshot.industries.filter((node) => ENERGY_SECTORS.has(node.industry) && !node.isRow && !node.isFinalDemand).map((node) => node.id)
    : [`${country}_${industry}`];
  if (!seed.length) return null;
  if (event.id !== 'oil-x2' && !manualAccepted) return null;
  const inputCost = event.id === 'oil-x2';
  if (inputCost ? [passLow, passHigh].some((value) => value.trim() === '') : [shockLow, shockHigh, subLow, subHigh, bufferLow, bufferHigh].some((value) => value.trim() === '')) return null;
  const shockLowValue = inputCost ? 1 : Number(shockLow);
  const shockHighValue = inputCost ? 1 : Number(shockHigh);
  const passLowValue = inputCost ? Number(passLow) / 100 : 0;
  const passHighValue = inputCost ? Number(passHigh) / 100 : 0;
  const subLowValue = Number(subLow) / 100;
  const subHighValue = Number(subHigh) / 100;
  const bufferLowValue = Number(bufferLow) / 100;
  const bufferHighValue = Number(bufferHigh) / 100;
  if ([shockLowValue, shockHighValue, subLowValue, subHighValue, bufferLowValue, bufferHighValue, passLowValue, passHighValue].some(Number.isNaN)) return null;
  if (shockLowValue < 0 || shockHighValue < shockLowValue || shockHighValue > (inputCost ? 10 : 100)) return null;
  if ([subLowValue, subHighValue, bufferLowValue, bufferHighValue, passLowValue, passHighValue].some((value) => value < 0 || value > 1)) return null;
  if (inputCost && passHighValue < passLowValue) return null;
  if (!inputCost && (subHighValue < subLowValue || bufferHighValue < bufferLowValue)) return null;
  if (!inputCost && !snapshot.industries.some((node) => node.id === seed[0])) return null;

  return {
    eventId, title: event.label, channel: inputCost ? 'input-cost' : 'production-outage', seedNodes: seed,
    shock: { min: shockLowValue / (inputCost ? 1 : 100), max: shockHighValue / (inputCost ? 1 : 100) },
    substitution: inputCost ? { min: 0, max: 0 } : { min: subLowValue, max: subHighValue },
    inventory: inputCost ? { min: 0, max: 0 } : { min: bufferLowValue, max: bufferHighValue },
    passThrough: inputCost ? { min: passLowValue, max: passHighValue } : { min: 0, max: 0 },
    seed: 2942026, samples: 61, maxSteps: 6,
  };
}

function TopIndustries({ result, onSelect }: { result: ScenarioResult; onSelect: (country: string) => void }) {
  const downstream = result.industries.filter((row) => row.step > 0);
  const max = Math.max(...downstream.map((row) => row.p90), 0.0001);
  return (
    <ol className="rank-list">
      {downstream.slice(0, 7).map((row, index) => (
        <li key={row.nodeId}>
          <button type="button" className="rank-row" onClick={() => onSelect(row.country)} aria-label={`${row.country} ${row.industryJa}の条件付き影響を地図上で選択`}>
            <span className="rank-index">{String(index + 1).padStart(2, '0')}</span>
            <span className="rank-info"><b>{row.industryJa}</b><small>{row.country} / {row.industry} · {row.step === 0 ? '入力ショック' : `第 ${row.step} 層`}</small><i className="impact-track"><i style={{ width: `${Math.max(2, (row.p50 / max) * 100)}%` }} /></i></span>
            <span className="rank-value">{percent(row.p50)}</span>
          </button>
        </li>
      ))}
      {downstream.length === 0 && <li className="empty-note">この条件では下流への有効波及が検出されませんでした。入力ショックは波及結果と分けて保存されます。</li>}
    </ol>
  );
}

function FindingLine({ label, value }: { label: string; value: string }) {
  return <div className="finding-line"><span>{label}</span><b>{value}</b></div>;
}

function CompanyProxy({ firms, impacts }: { firms: FirmRecord[]; impacts: IndustryImpact[] }) {
  const jp = impacts.filter((node) => node.country === 'JPN' && node.step > 0);
  const candidates = jp.slice(0, 5).flatMap((node) => {
    const matches = firms.filter((firm) => firm.industryNode === node.nodeId).slice(0, 4);
    return matches.map((firm) => ({ firm, node }));
  });
  if (!jp.length || !candidates.length) return <div className="empty-note">日本上場企業への個社取引リンクがなく、個社損失は算定しません。該当産業の企業名簿は企業名鑑から参照できます。</div>;
  return (
    <div className="proxy-grid">
      {candidates.slice(0, 12).map(({ firm, node }) => (
        <article className="proxy-card" key={`${firm.id}-${node.nodeId}`}>
          <div className="proxy-card__signal"><span>業種代理</span><span>+{percent(node.p50)}</span></div>
          <b>{firm.name}</b><small>{firm.ticker ?? 'コード未記録'} · {node.industryJa}</small>
          <p>産業平均の感度です。この企業の仕入関係・依存率や固有売上の損失ではありません。</p>
        </article>
      ))}
    </div>
  );
}

function CoverageStatus({ snapshot }: { snapshot: Snapshot }) {
  const productive = snapshot.industries.filter((node) => !node.isRow && !node.isFinalDemand);
  const eventNodes = new Set(productive.filter((node) => node.country !== 'ROW').map((node) => node.country));
  const companies = Number(snapshot.manifest.counts.japanListedCompanies ?? 0);
  const relations = Number(snapshot.manifest.counts.ownershipRelationships ?? 0);
  return (
    <div className="coverage-strip" aria-label="データ適用範囲">
      <div><span className="coverage-strip__mark coverage-strip__mark--blue" /><b>{eventNodes.size.toLocaleString('ja-JP')}</b><small>カバー国</small></div>
      <div><span className="coverage-strip__mark coverage-strip__mark--red" /><b>{productive.length.toLocaleString('ja-JP')}</b><small>生産IOノード</small></div>
      <div><span className="coverage-strip__mark coverage-strip__mark--green" /><b>{companies.toLocaleString('ja-JP')}</b><small>日本上場企業</small></div>
      <div><span className="coverage-strip__mark coverage-strip__mark--amber" /><b>{relations.toLocaleString('ja-JP')}</b><small>資本関係（取引でない）</small></div>
    </div>
  );
}

function ProvenanceCard({ snapshot, onNavigate }: { snapshot: Snapshot; onNavigate: (page: Page) => void }) {
  return (
    <div className="source-strip">
      <div className="source-strip__intro"><BookOpen size={16} /><span>TRANSPARENT BY DESIGN</span></div>
      <p>観測事実・産業代理・利用者仮定を混ぜません。<button type="button" className="text-link" onClick={() => onNavigate('data')}>データ台帳で出典を見る<ArrowUpRight size={13} /></button></p>
      <div className="source-badges"><span>OECD ICIO · 2020</span><span>JP listed · {snapshot.companies.length.toLocaleString('ja-JP')}</span><span>企業間仕入 · 未観測</span></div>
    </div>
  );
}

function DataPage({ snapshot }: { snapshot: Snapshot }) {
  const { manifest } = snapshot;
  const ownershipCount = Number(manifest.counts.ownershipRelationships ?? 0);
  return (
    <div className="single-layout">
      <section className="panel data-panel">
        <div className="section-head section-head--line"><div><Slot>DATA / SOURCES / VERSION</Slot><h2>データの系譜</h2></div><span className="count-badge">{manifest.schemaVersion}</span></div>
        <p className="panel-lead">数だけでは、データの意味は保証されない。時点・粒度・利用条件・このアプリ内での使い方をそれぞれ開示する。</p>
        <div className="version-card"><div><span className="eyebrow">SOURCE SNAPSHOT COMMIT</span><code>{manifest.datasetSnapshot}</code></div><div><span className="eyebrow">GENERATED AT</span><code>{new Date(manifest.generatedAt).toLocaleString('ja-JP')}</code></div><div><span className="eyebrow">COUNTRY BOUNDARY</span><code>Natural Earth 1:110m · de facto</code></div></div>
        <div className="table-scroll"><table className="source-table"><thead><tr><th>データセット</th><th>期間</th><th>用途・非用途</th><th>利用条件</th><th>原典</th></tr></thead><tbody>
          {manifest.dataCatalog.map((row) => <tr key={row.id}><td><strong>{row.label}</strong><small>{row.id}</small></td><td>{row.period}</td><td>{row.role}</td><td>{row.license}</td><td>{row.source.startsWith('http') ? <a href={row.source} target="_blank" rel="noreferrer">出典へ <ArrowUpRight size={12} /></a> : row.source}</td></tr>)}
        </tbody></table></div>
        <div className="source-gap"><div className="source-gap__badge"><Info size={16} />未収録・未接続</div><ul>{manifest.exclusions.map((entry) => <li key={entry}>{entry}</li>)}</ul></div>
        <details className="checksums"><summary>スナップショットのSHA-256（全{Object.keys(manifest.checksumsSha256).length}件）</summary><div>{Object.entries(manifest.checksumsSha256).map(([file, sha]) => <div key={file}><code>{file}</code><code>{sha}</code></div>)}</div></details>
        <p className="micro-note">ソースコードはApache-2.0。データや第三者資料は各権利者の条件が別に適用されます。利用条件を確認できていないファイルを自由に再配布できるとは表示しません。</p>
      </section>
      <section className="panel method-panel">
        <div className="section-head section-head--line"><div><Slot>MODEL / LIMITS / REPRODUCIBILITY</Slot><h2>計算の境界</h2></div><Orbit size={18} /></div>
        <div className="method-columns">
          <article><span>01 / 流れ</span><h3>IO伝播</h3><p>buyer × seller間のICIO投入係数を上流から順に適用する。国×産業の生産中断 proxy は、利用者が指定したショックを起点に、固定的な中間投入構造を通じて伝播する。</p></article>
          <article><span>02 / 金融換算</span><h3>変換しない</h3><p>購買・利益・売上、時価総額、倒産に校正されていない。企業間取引と財務値が存在しないため、企業固有損失・企業倒産確率は予測しない。</p></article>
          <article><span>03 / 感度</span><h3>入力値の幅</h3><p>P10/P50/P90は画面に明示された仮定範囲を一様に掃引した条件付き分位。事象発生確率、信頼区間、過去検証済みの予測区間ではない。</p></article>
          <article><span>04 / 重複</span><h3>取引と資本を分離</h3><p>{ownershipCount.toLocaleString('ja-JP')}件の資本関係はIO投入係数と合算しない。企業別の取引フローは未観測なので、観測経路をIO経路へ置き換える処理はまだ行わない。</p></article>
          <article><span>05 / 検証</span><h3>未校正を表示</h3><p>この製品版は歴史的事象のバックテストが完了していない。テストはソースコードの数式・再現性・不変条件を検査するもので、未来予測の的中率ではない。</p></article>
          <article><span>06 / 共有</span><h3>条件込みで再現</h3><p>実行シード、全ショック仮定、入力ノード、データ版をScenario Bundleと共に保管し、前提の違いを読み比べる。</p></article>
        </div>
        <div className="method-citation"><Database size={15} /><span><b>係数と国別集計：</b>{manifest.ioModelDefinition.coefficient} 係数0.0005未満は非収録。{manifest.ioModelDefinition.terminalDemandColumns} {manifest.ioModelDefinition.countryAggregation}企業別仕入先の観測記録ではありません。</span></div>
      </section>
    </div>
  );
}

function EventsPage({ onSelect }: { onSelect: (id: string) => void }) {
  return (
    <section className="panel catalog-panel">
      <div className="section-head section-head--line"><div><Slot>EVENT CATALOG · 11 SCENARIOS</Slot><h2>どの事象を、何で計算できるか</h2></div><span className="count-badge">11 use cases</span></div>
      <p className="panel-lead">一つのショック伝播モデルを使いますが、全部のイベントが観測済み、あるいは算定可能なわけではありません。ステータスは実データに応じて変えています。</p>
      <div className="event-catalog">{EVENTS.map((event, index) => (
        <article className={`event-card event-card--${event.support}`} key={event.id}>
          <span className="event-card__number">{String(index + 1).padStart(2, '0')}</span>
          <div className="event-card__body"><div className="event-card__header"><h3>{event.label}</h3><span className={`evidence-tag evidence-tag--${event.support}`}>{event.support === 'conditional' ? '条件付き' : event.support === 'proxy-only' ? '代理入力のみ' : '算定不可'}</span></div><p>{event.method}</p><small><b>必要条件：</b>{event.boundary}</small><small><b>現在の根拠：</b>{event.sourceKind}</small></div>
          <button type="button" className="arrow-button" onClick={() => onSelect(event.id)} aria-label={`${event.label}のシナリオ入力へ`}><ArrowRight size={16} /></button>
        </article>
      ))}</div>
      <div className="alert-band"><CircleAlert size={17} /><p><b>ルート閉鎖・銀行破綻・港湾閉鎖を自動計算するふりはしません。</b>対応関係がない事象は、実際のイベント経路として算定不可です。国×産業停止の代理入力に切り替えた場合は、イベントそのものと別の仮定として扱います。</p></div>
    </section>
  );
}

function ScenarioAnalysis({
  snapshot, initialEventId, onChoosePage, onRun, running, progress, result: rawResult, error,
}: {
  snapshot: Snapshot; initialEventId: string; onChoosePage: (page: Page) => void; onRun: (input: ScenarioInput) => void;
  running: boolean; progress: number; result: ScenarioResult | null; error: string | null;
}) {
  const [eventId, setEventId] = useState(initialEventId);
  const [country, setCountry] = useState('TWN');
  const [industry, setIndustry] = useState('C26');
  const [manualAccepted, setManualAccepted] = useState(false);
  const [shockLow, setShockLow] = useState('');
  const [shockHigh, setShockHigh] = useState('');
  const [subLow, setSubLow] = useState('0');
  const [subHigh, setSubHigh] = useState('0');
  const [bufferLow, setBufferLow] = useState('0');
  const [bufferHigh, setBufferHigh] = useState('0');
  const [passLow, setPassLow] = useState('0');
  const [passHigh, setPassHigh] = useState('100');
  const [selectedCountry, setSelectedCountry] = useState<string | null>(null);
  const [bundleNotice, setBundleNotice] = useState('');
  const [savedRuns, setSavedRuns] = useState<SavedRun[]>(() => {
    try { return JSON.parse(localStorage.getItem('ripple:runs') ?? '[]') as SavedRun[]; } catch { return []; }
  });

  const spec = EVENTS.find((event) => event.id === eventId) ?? EVENTS[0];
  const hasOilProxy = eventId === 'oil-x2';
  const scenario = useMemo(() => buildScenario({
    eventId, snapshot, country, industry, manualAccepted, shockLow, shockHigh,
    subLow, subHigh, bufferLow, bufferHigh, passLow, passHigh,
  }), [eventId, snapshot, country, industry, manualAccepted, shockLow, shockHigh, subLow, subHigh, bufferLow, bufferHigh, passLow, passHigh]);
  const result = rawResult && scenario && JSON.stringify(rawResult.input) === JSON.stringify(scenario) ? rawResult : null;
  const countries = useMemo(() => [...new Set(snapshot.industries.filter((node) => !node.isRow && !node.isFinalDemand && node.country !== 'ROW').map((node) => node.country))].sort(), [snapshot.industries]);
  const sectors = useMemo(() => [...new Set(snapshot.industries.filter((node) => node.country === country && !node.isFinalDemand).map((node) => node.industry))].sort(), [snapshot.industries, country]);
  const originalCountry = snapshot.world.features.find((feature) => feature.properties.iso3 === country)?.properties.name ?? country;
  const mapImpacts = result?.countries ?? [];
  const canCalculate = scenario !== null && (!running) && (hasOilProxy || (manualAccepted && shockLow !== '' && shockHigh !== ''));

  // Never continue labelling a previous run as the current scenario after an input changes.
  useEffect(() => {
    setEventId(initialEventId);
    setManualAccepted(false);
  }, [initialEventId]);

  useEffect(() => {
    if (!sectors.includes(industry) && sectors.length) setIndustry(sectors.includes('C26') ? 'C26' : sectors[0]);
  }, [country, sectors, industry]);

  const handleRun = () => { if (scenario) onRun(scenario); };
  const addSavedRun = () => {
    if (!result) return;
    const key = `${result.input.eventId}:${result.input.seed}:${result.input.seedNodes.join(',')}:${Date.now()}`;
      const run: SavedRun = { key, title: result.input.title, when: new Date().toISOString(), input: result.input, top: result.industries.filter((item) => item.step > 0).slice(0, 7).map(({ nodeId, country: code, industryJa, p50 }) => ({ nodeId, country: code, industryJa, p50 })) };
    const next = [run, ...savedRuns].slice(0, 6);
    setSavedRuns(next);
    localStorage.setItem('ripple:runs', JSON.stringify(next));
    setBundleNotice('比較用に保存しました');
  };
  const downloadBundle = () => {
    if (!result) return;
    const bundle: ScenarioBundle = {
      schemaVersion: 'ripple-scenario/1.2', codeRevision: __RIPPLE_SOURCE_REVISION__, modelVersion: MODEL_VERSION,
      datasetSnapshot: snapshot.manifest.datasetSnapshot,
      datasetGeneratedAt: snapshot.manifest.generatedAt,
      datasetChecksumsSha256: snapshot.manifest.checksumsSha256,
      createdAt: new Date().toISOString(),
      sourceStatus: 'observed-data-plus-explicit-assumptions', scenario: result.input, results: result,
      interpretation: [
        '入力ショックと独立した事象発生確率ではありません。',
        'P10/P50/P90は入力範囲を一様に掃引した感度分位です。校正済予測区間ではありません。',
        '対象の主張はICIO 2020の国×産業投入係数に基づく条件付きストレス指標です。',
        '日本企業に関しては個社別仕入フロー・生産位置を観測していません。会社行は産業代理であり会社固有の損失値ではありません。',
      ],
    };
    saveBlob(`ripple-scenario-${result.input.eventId}-${result.input.seed}.json`, JSON.stringify(bundle, null, 2), 'application/json');
    setBundleNotice('コードrevision・前提・データ版・結果を含むScenario Bundleを保存しました');
  };
  const downloadCsv = () => {
    if (!result) return;
    const columns = ['node_id', 'country', 'industry', 'industry_label_ja', 'first_step', 'sensitivity_p10', 'sensitivity_p50', 'sensitivity_p90'];
    const rows = result.industries.map((item) => [item.nodeId, item.country, item.industry, item.industryJa, item.step, item.p10, item.p50, item.p90]);
    const csv = [columns, ...rows].map((row) => row.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(',')).join('\r\n');
    saveBlob(`ripple-industries-${result.input.eventId}.csv`, '\uFEFF' + csv, 'text/csv;charset=utf-8');
  };
  return (
    <main className="workbench" id="main-content">
      <div className="hero-row">
        <div className="hero-copy"><Slot>OPEN WORLD-SYSTEM STRESS LAB&nbsp; / &nbsp;MODEL 0.1</Slot><h1>どの出来事から、<br /><span>何が先に揺れるか。</span></h1><p>問いを置き、国×産業の構造に沿って条件付きの波及をたどる。<b>予測確率でも企業別の業績見通しでもありません。</b></p></div>
        <div className="hero-side"><div className="hero-side__top"><span className="status-chip"><span /> SNAPSHOT LOADED</span><span className="mono">ICIO / 2020</span></div><h2>実験環境の適用範囲</h2><p>観測できるのは世界の国×産業構造と、日本上場企業の基礎情報です。企業別の仕入依存は未観測。</p><CoverageStatus snapshot={snapshot} /></div>
      </div>

      <section className="experiment-layout" aria-label="シナリオ入力と結果">
        <aside className="experiment-rail panel">
          <div className="rail-head"><div><Slot>SCENARIO INPUT</Slot><h2>条件を置く</h2></div><span className="rail-step">01 <i>/</i> 04</span></div>
          <label className="field-label" htmlFor="event-select">事象</label>
          <div className="select-shell"><select id="event-select" value={eventId} onChange={(event) => { setEventId(event.target.value); setManualAccepted(false); }}>
            {EVENTS.map((event) => <option value={event.id} key={event.id}>{event.label} · {event.support === 'unavailable' ? '算定不可' : event.support === 'proxy-only' ? '代理のみ' : '条件付'}</option>)}
          </select><ChevronDown size={15} /></div>
          <div className={`scenario-status scenario-status--${spec.support}`}>
            {spec.support === 'unavailable' ? <ShieldAlert size={15} /> : spec.support === 'conditional' ? <Check size={15} /> : <CircleAlert size={15} />}
            <span>{spec.support === 'conditional' ? '限定的に接続された指標' : spec.support === 'proxy-only' ? '代理入力が必要' : 'データ接続がなく算定不可'}</span>
          </div>
          <p className="scenario-method">{spec.method}</p>

          {hasOilProxy ? (
            <div className="proxy-conditions">
              <div className="proxy-callout"><strong>2×</strong><span><b>+100% 価格入力</b><small>シナリオ指定に基づく。原油単独の系列ではない。</small></span></div>
              <div className="seed-summary"><span>対象投入ノード</span><b>{scenario?.seedNodes.length ?? 0}ノード · B05_06</b><small>石炭・原油・天然ガス採掘の集計。原油のみを分離できません。</small></div>
              <RangePair label="費用への価格転嫁率（未校正・仮定）" low={passLow} high={passHigh} onLow={setPassLow} onHigh={setPassHigh} />
              <p className="control-note">表示初期値0–100%は事実ではなく、未転嫁から全額転嫁までの感度探索範囲です。転嫁率は観測していません。</p>
            </div>
          ) : (
            <div className="proxy-conditions">
              <label className="proxy-consent"><input type="checkbox" checked={manualAccepted} onChange={(event) => setManualAccepted(event.target.checked)} /><span>イベント経路ではなく、国×産業への供給途絶を代理入力する</span></label>
              <label className="field-label" htmlFor="country-select">供給起点の国（利用者指定）</label>
              <div className="select-shell"><select id="country-select" value={country} onChange={(event) => setCountry(event.target.value)}>{countries.map((code) => {
                const name = snapshot.world.features.find((feature) => feature.properties.iso3 === code)?.properties.name ?? code;
                return <option key={code} value={code}>{name} / {code}</option>;
              })}</select><ChevronDown size={15} /></div>
              <label className="field-label" htmlFor="industry-select">供給産業（ICIOの広い分類）</label>
              <div className="select-shell"><select id="industry-select" value={industry} onChange={(event) => setIndustry(event.target.value)}>{sectors.map((code) => <option key={code} value={code}>{snapshot.industries.find((node) => node.id === `${country}_${code}`)?.industryJa ?? code} · {code}</option>)}</select><ChevronDown size={15} /></div>
              <div className="seed-summary"><span>代理ショック範囲</span><small>{originalCountry}・{industry}の国×産業のみ。海峡・企業工場・港湾ルートは再現しません。</small></div>
              <RangePair label="当該産業の供給途絶率（利用者仮定）" low={shockLow} high={shockHigh} onLow={setShockLow} onHigh={setShockHigh} />
              <RangePair label="代替調達率（仮定）" low={subLow} high={subHigh} onLow={setSubLow} onHigh={setSubHigh} />
              <RangePair label="在庫による吸収率（仮定）" low={bufferLow} high={bufferHigh} onLow={setBufferLow} onHigh={setBufferHigh} />
              <p className="control-note">代替・在庫の初期値はそれぞれ0%です。データ上の観測ではなく「吸収なし」の基準ケース。違う値にする場合は範囲を編集してください。</p>
            </div>
          )}
          {error && <div role="alert" className="error-callout"><CircleAlert size={16} />{error}</div>}
          {!scenario && <p className="control-note">実行するには空欄を埋め、各仮定の下限が上限以下であることを確認してください。</p>}
          <button type="button" className="run-button" onClick={handleRun} disabled={!canCalculate}>
            {running ? <><span className="spinner" />伝播を計算中…</> : <><Play size={15} fill="currentColor" /> 条件付き伝播を計算</>}
          </button>
          {running && <div className="progress-block"><div className="progress-track"><i style={{ width: `${progress}%` }} /></div><span>{progress}% · ブラウザー内の一時計算</span></div>}
          <div className="sensitivity-note"><Info size={14} /><p><b>P10 / P50 / P90</b>は設定した入力範囲の感度分位。発生確率・将来予測・信頼区間ではありません。</p></div>
        </aside>

        <div className="map-column">
          <section className="map-panel panel" aria-label="世界地図の国×産業露出">
            <div className="panel-titlebar"><div><Slot>ATLAS / COVERED SECTORS ONLY</Slot><h2>世界の伝播面</h2></div><div className="map-control-hint"><span className="hollow-dot" /> 港の位置（6件）<i /> 経路の線は未収録</div></div>
            {result ? (
              <div className="map-current"><span className="map-current__event">{result.input.title}</span><span>{result.summary.channel === 'input-cost' ? '影響セクター単純平均 · 費用圧力proxy P50' : '影響セクター単純平均 · 生産中断proxy P50'}</span></div>
            ) : <div className="map-current map-current--empty"><span>シミュレーション結果は未実行</span><span>シナリオ条件を計算すると色づきます</span></div>}
            <WorldMap world={snapshot.world} impacts={mapImpacts} ports={snapshot.ports} selectedCountry={selectedCountry} onSelectCountry={setSelectedCountry} />
            <div className="map-foot"><span>Natural Earth 1:110m · de facto 国境</span><span>灰色＝ゼロではなく、非収録／この実行では未波及</span></div>
          </section>
          <div className="trace-panel panel">
            <div className="trace-panel__title"><div><Slot>TRANSMISSION ORDER</Slot><h3>ショックから、産業へ</h3></div><GitBranch size={16} /></div>
            <div className="transmission-flow">
              <div className={result ? 'flow-stage flow-stage--active' : 'flow-stage'}><span>00</span><b>{hasOilProxy ? '価格仮定' : '直接の産業ショック'}</b><small>{hasOilProxy ? '入力ノード' : '利用者指定'}</small></div>
              <ArrowRight size={16} />
              <div className={result?.industries.some((row) => row.step === 1) ? 'flow-stage flow-stage--active' : 'flow-stage'}><span>01</span><b>国×産業</b><small>OECD · 2020</small></div>
              <ArrowRight size={16} />
              <div className="flow-stage flow-stage--muted"><span>02</span><b>日本上場企業</b><small>個社仕入リンクなし</small></div>
            </div>
            <div className="trace-caption"><span>波及段数は経済の経過時間ではありません</span><span>同じIO接続は同一ネットワーク内でのみ反映</span></div>
          </div>
        </div>

        <aside className="analysis-column">
          <section className="first-wave panel">
            <div className="section-head"><div><Slot>FIRST RIPPLES</Slot><h2>最初に触れる産業</h2></div><span className="first-wave__icon"><Activity size={15} /></span></div>
            {result ? <>
              <div className="result-summary"><span>条件付き産業ノード</span><b>{result.summary.affectedIndustryCount}</b><small>{result.summary.distributionLabel}</small></div>
              <TopIndustries result={result} onSelect={setSelectedCountry} />
              <div className="range-legend"><span>感度レンジ / P10</span><span>中央値 / P50</span><span>感度レンジ / P90</span></div>
            </> : <div className="empty-result"><span className="empty-result__circle"><Sparkles size={17} /></span><b>ショックの起点を設定してください</b><p>利用可能なデータから直接影響先が無ければ、結果もゼロで埋めずに不足として表示します。</p></div>}
            <div className="first-wave__method"><CircleAlert size={14} /><span>IO伝播は固定的な係数構造のproxy。欠品日数・企業売上・利益・株価に読み替えません。</span></div>
          </section>
          {result && (
            <section className="country-breakdown panel">
              <div className="section-head"><div><Slot>GEOGRAPHIC SUMMARY</Slot><h3>国の波及候補</h3></div><span className="micro-count">{result.countries.length} 地域</span></div>
              <p>その国で結果が出たIO業種の等重み平均。国民経済の予測ではありません。</p>
              {result.countries.slice(0, 4).map((country, index) => <button type="button" className="country-row" key={country.country} onClick={() => setSelectedCountry(country.country)}><span>{String(index + 1).padStart(2, '0')}</span><b>{snapshot.world.features.find((feature) => feature.properties.iso3 === country.country)?.properties.name ?? country.country}</b><small>{country.coveredIndustries}産業</small><strong>{percent(country.p50)}</strong></button>)}
            </section>
          )}
        </aside>
      </section>

      {result && <div className="post-analysis">
        <section className="panel firm-proxy-panel">
          <div className="section-head section-head--line"><div><Slot>JAPAN · COMPANY-LEVEL EVIDENCE LIMIT</Slot><h2>日本上場企業への見え方</h2></div><button type="button" className="text-link" onClick={() => onChoosePage('companies')}>企業名鑑を見る <ArrowUpRight size={14} /></button></div>
          <div className="proxy-caution"><Building2 size={17} /><p>産業レベルの波及を会社別損失へ変換しません。事業領域と仕入先が分からない状態では、企業の違いが出る個社ランキングは作れません。下の例は対応する日本産業に属する企業名と共有産業指標の表示に限ります。</p></div>
          <CompanyProxy firms={snapshot.companies} impacts={result.industries} />
        </section>
        <section className="panel run-panel">
          <div className="section-head section-head--line"><div><Slot>REPRODUCE / EXPORT / COMPARE</Slot><h2>この条件を持ち帰る</h2></div><FileJson2 size={19} /></div>
          <div className="run-metadata">
            <FindingLine label="モデル" value={`RIPPLE ${MODEL_VERSION} / ${result.summary.maxPropagationSteps}層`} />
            <FindingLine label="データ" value="OECD ICIO 2020 · ICIO係数固定" />
            <FindingLine label="コードrevision" value={__RIPPLE_SOURCE_REVISION__.slice(0, 12)} />
            <FindingLine label="再現seed" value={String(result.input.seed)} />
            <FindingLine label="感度試行" value={`${result.summary.samples} draws / 一様入力感度`} />
            <FindingLine label="入力前提" value={result.input.seedNodes.length > 8 ? `${result.input.seedNodes.length} seed nodes` : result.input.seedNodes.join(', ')} />
          </div>
          <div className="export-actions"><button type="button" onClick={downloadBundle} className="button-primary"><Download size={15} /> Scenario Bundle · JSON</button><button type="button" onClick={downloadCsv} className="button-quiet"><Table2 size={15} /> 国産業 CSV</button><button type="button" onClick={addSavedRun} className="button-quiet"><Clipboard size={15} /> 比較へ保存</button></div>
          {bundleNotice && <span className="inline-confirm"><Check size={13} />{bundleNotice}</span>}
          {savedRuns.length > 0 && <div className="saved-compare"><div className="saved-compare__head"><span>保存した条件比較</span><span>端末内のみ · {savedRuns.length}/6</span></div>{savedRuns.slice(0, 3).map((run) => <div className="saved-run" key={run.key}><span className="saved-run__dot" /> <b>{run.title}</b><small>{new Date(run.when).toLocaleString('ja-JP', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</small><span>{run.top[0] ? `${run.top[0].country} / ${run.top[0].industryJa}` : '影響ノードなし'}</span></div>)}{savedRuns.length > 1 && <details className="compare-table"><summary>上位ノードを並べて比較</summary>{savedRuns.slice(0, 2).map((run) => <div key={`cmp-${run.key}`}><b>{run.title}</b>{run.top.slice(0, 5).map((item) => <FindingLine key={`${run.key}-${item.nodeId}`} label={`${item.country} / ${item.industryJa}`} value={percent(item.p50)} />)}</div>)}</details>}</div>}
          <p className="micro-note">ブラウザー上で保存・比較できます。Scenario Bundleにはデータ版・生成時刻・実ファイルのSHA-256を記録し、データページで出典を確認できます。APIキーや個別アカウント情報は含めません。</p>
        </section>
      </div>}
      {!result && <ProvenanceCard snapshot={snapshot} onNavigate={onChoosePage} />}
      <div className="bottom-disclaimer"><ShieldAlert size={15} /><span>条件付きストレステスト。バックテスト未校正。投資助言、信用評価、企業別業績予測ではありません。</span><span className="bottom-disclaimer__v">SNAPSHOT&nbsp; 2026 · MODEL 0.1</span></div>
    </main>
  );
}

function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [page, setPage] = useState<Page>('atlas');
  const [result, setResult] = useState<ScenarioResult | null>(null);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [simulationError, setSimulationError] = useState<string | null>(null);
  const [pendingEvent, setPendingEvent] = useState(DEFAULT_EVENT_ID);

  useEffect(() => {
    let alive = true;
    loadSnapshot().then((data) => { if (alive) setSnapshot(data); }).catch((error: unknown) => {
      if (alive) setLoadError(error instanceof Error ? error.message : 'Data snapshot could not be loaded.');
    }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  const onRun = useCallback(async (scenario: ScenarioInput) => {
    setRunning(true); setProgress(0); setSimulationError(null); setResult(null);
    try {
      const snapshotForWorker = snapshot;
      if (!snapshotForWorker) throw new Error('Data is not loaded.');
      const [flowsBuffer] = await Promise.all([readFlowSnapshot()]);
      const worker = new Worker(new URL('./engine/simulation.worker.ts', import.meta.url), { type: 'module' });
      const simulation = await new Promise<ScenarioResult>((resolve, reject) => {
        worker.onmessage = (message: MessageEvent) => {
          if (message.data.type === 'progress') setProgress(Math.min(99, Math.floor((message.data.completed / Math.max(message.data.total, 1)) * 100)));
          if (message.data.type === 'result') resolve(message.data.result as ScenarioResult);
          if (message.data.type === 'error') reject(new Error(String(message.data.message)));
        };
        worker.onerror = () => reject(new Error('Web Worker failed to execute the scenario.'));
        worker.postMessage({ type: 'simulate', scenario, nodes: snapshotForWorker.industries, flowsBuffer }, [flowsBuffer]);
      }).finally(() => worker.terminate());
      setResult(simulation); setProgress(100);
    } catch (error) {
      setSimulationError(error instanceof Error ? error.message : 'Could not run the scenario.');
    } finally { setRunning(false); }
  }, [snapshot]);

  const navigateToEvent = (eventId: string) => { setPendingEvent(eventId); setPage('atlas'); window.scrollTo({ top: 0, behavior: 'smooth' }); };

  if (loading) return <div className="app-frame"><div className="loading-state"><div className="brand-mark"><RippleGlyph size={20} /></div><p>出典付き経済データを読込中…</p><span>データの系譜を確認しています</span></div></div>;
  if (loadError || !snapshot) return <div className="app-frame"><div className="fatal-state"><CircleAlert size={22} /><h1>データスナップショットを開けません</h1><p>{loadError ?? 'Manifest is unavailable.'}</p><p>欠損したデータをゼロ値で置き換えず、画面を停止しています。</p></div></div>;

  return (
    <div className="app-frame">
      <a className="skip-link" href="#main-content">本文へ移動</a>
      <header className="topbar">
        <div className="brand"><span className="brand-mark" aria-hidden="true"><RippleGlyph size={18} /></span><span className="brand-type"><b>RIPPLE</b><small>WORLD-SYSTEM STRESS LAB</small></span></div>
        <nav className="main-nav" aria-label="メインナビゲーション">{NAV.map(({ id, label, icon: Icon }) => <button key={id} type="button" className={page === id ? 'nav-button nav-button--active' : 'nav-button'} onClick={() => setPage(id)} aria-current={page === id ? 'page' : undefined}><Icon size={15} />{label}</button>)}</nav>
        <div className="topbar-status"><span className="status-chip"><span /> SNAPSHOT</span><span className="topbar-status__date">{new Date(snapshot.manifest.generatedAt).toISOString().slice(0, 10).replaceAll('-', '.')}</span></div>
      </header>
      <div className="ticker-line"><span>OPEN RESEARCH WORKBENCH</span><i /> <span>2020 ICIO STRUCTURAL BASELINE</span><i /> <span>CONDITIONAL SCENARIO · NOT A FORECAST</span><span className="ticker-line__right">MODEL {MODEL_VERSION}</span></div>
      {page === 'atlas' && <ScenarioAnalysis snapshot={snapshot} initialEventId={pendingEvent} onChoosePage={setPage} onRun={onRun} running={running} progress={progress} result={result} error={simulationError} />}
      {page === 'companies' && <div id="main-content" className="page-shell"><div className="page-heading"><Slot>COMPANY REFERENCE</Slot><h1>関係が見える企業、<br />まだ見えない依存。</h1><p>会社別の仕入関係は未収録。見えている資本関係と業種カバレッジだけを検索できます。</p></div><CompanyDirectory companies={snapshot.companies} ownership={snapshot.ownership} /></div>}
      {page === 'data' && <div id="main-content" className="page-shell"><div className="page-heading"><Slot>DATA / METHOD</Slot><h1>測ったものと、<br />まだ分からないこと。</h1><p>データの取得期間、粒度、出典、欠損を隠さず、数値を解釈するときの境界を共有します。</p></div><DataPage snapshot={snapshot} /></div>}
      {page === 'events' && <div id="main-content" className="page-shell"><div className="page-heading"><Slot>EVENT COVERAGE</Slot><h1>同じエンジンで。<br />同じ精度とは限らない。</h1><p>事象はショック条件へ変換できます。現データの範囲外は、算定不可と区別しています。</p></div><EventsPage onSelect={navigateToEvent} /></div>}
      <footer className="app-footer"><div className="app-footer__brand"><RippleGlyph size={15} /> RIPPLE <span>Open-source research workbench</span></div><div><a href="https://github.com/socratesyama/cyber-economy-map" target="_blank" rel="noreferrer">Source repository <ArrowUpRight size={12} /></a><span>Apache-2.0 · Data terms are source-specific</span></div></footer>
    </div>
  );
}

export default App;
