import { useMemo, useRef, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { ArrowUpRight, Building2, Search } from 'lucide-react';
import type { FirmRecord, OwnershipRecord } from './engine/types';

interface Props {
  companies: FirmRecord[];
  ownership: OwnershipRecord[];
}

function EvidenceDetail({ company, ownership }: { company: FirmRecord; ownership: OwnershipRecord[] }) {
  const related = ownership.filter((edge) => edge.src_id === company.id || edge.dst_id === company.id).slice(0, 18);
  return (
    <aside className="firm-detail" aria-live="polite">
      <div className="firm-detail__eyebrow"><Building2 size={14} /> SELECTED LISTED COMPANY</div>
      <h3>{company.name}</h3>
      <div className="firm-detail__facts">
        <span>銘柄コード <b>{company.ticker ?? '記録なし'}</b></span>
        <span>業種 <b>{company.sector ?? '分類なし'}</b></span>
        <span>個社財務フィールド <b>{company.tier1FinancialRecordCount > 0 ? `ファイル ${company.tier1FinancialRecordCount}件` : 'この抽出では未収録'}</b></span>
      </div>
      <div className="firm-detail__notice">
        <b>個別の供給依存・シナリオ損失は未算定</b>
        <p>企業行は会社識別子と業種だけです。産業の波及値をこの会社固有の損失へ変換していません。</p>
      </div>
      <h4>開示・構造化された資本関係 ({related.length}{related.length === 18 ? '+' : ''})</h4>
      {related.length === 0 ? <p className="empty-note">この企業について、抽出対象の関係リンクが登録されていません。</p> : (
        <ul className="evidence-list">
          {related.map((edge) => {
            const counterpart = edge.src_id === company.id ? edge.dst_id : edge.src_id;
            return (
              <li key={edge.edge_id}>
                <span className={`evidence-tag evidence-tag--${edge.dependency_status}`}>{edge.dependency_status === 'observed_value' ? '開示値' : edge.dependency_status === 'observed_binary' ? '関係観測' : edge.dependency_status}</span>
                <span className="evidence-list__text">{edge.src_id === company.id ? '関係先' : '親・出資元'} <code>{counterpart}</code>
                  {edge.share_pct !== null && <b className="mono">{Number(edge.share_pct).toFixed(1)}%</b>}
                  <small> {edge.relation_type} · {edge.as_of || '日付記録なし'} · tier {edge.source_tier}</small>
                </span>
                {edge.source_ref?.startsWith('http') ? <a href={edge.source_ref} target="_blank" rel="noreferrer" aria-label="元資料を別タブで開く"><ArrowUpRight size={14} /></a> : null}
              </li>
            );
          })}
        </ul>
      )}
      <p className="micro-note">資本関係は仕入・販売・貸付ではありません。出典URLは公開識別子を指すものだけ表示します。</p>
    </aside>
  );
}

export function CompanyDirectory({ companies, ownership }: Props) {
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<FirmRecord | null>(null);
  const list = useMemo(() => {
    const term = query.trim().toLocaleLowerCase('ja-JP');
    if (!term) return companies;
    return companies.filter((company) => [company.name, company.ticker ?? '', company.sector ?? '']
      .some((value) => value.toLocaleLowerCase('ja-JP').includes(term)));
  }, [companies, query]);
  const parentRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: list.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 58,
    overscan: 12,
  });

  return (
    <section className="directory-layout">
      <div className="directory-panel panel">
        <div className="section-head section-head--line">
          <div><span className="eyebrow">JAPAN · LISTED EQUITIES</span><h2>企業ディレクトリ</h2></div>
          <span className="count-badge">{list.length.toLocaleString('ja-JP')} / {companies.length.toLocaleString('ja-JP')}</span>
        </div>
        <label className="search-field">
          <Search size={16} aria-hidden="true" />
          <span className="sr-only">会社名・証券コード・業種で検索</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="会社名・証券コード・業種" />
        </label>
        <p className="table-hint">各社の取引先を示す一覧ではありません。検索後に企業を開くと、会社識別子と記録済みの資本関係だけを確認できます。</p>
        <div className="firm-table" role="table" aria-label="日本上場企業の企業ディレクトリ" aria-rowcount={list.length + 1}>
        <div role="rowgroup"><div className="firm-grid firm-grid--header" role="row">
          <span role="columnheader">会社</span><span role="columnheader">銘柄</span><span role="columnheader">JPX業種</span><span role="columnheader">記録</span>
        </div></div>
        <div className="virtual-table" ref={parentRef} role="rowgroup">
          <div className="virtual-table__spacer" style={{ height: `${virtualizer.getTotalSize()}px` }}>
            {virtualizer.getVirtualItems().map((item) => {
              const company = list[item.index];
              return (
                <div className={`firm-grid firm-grid--row ${selected?.id === company.id ? 'is-selected' : ''}`} role="row"
                  aria-rowindex={item.index + 2} key={company.id} style={{ transform: `translateY(${item.start}px)` }}>
                  <span role="cell" className="firm-name-cell"><button type="button" onClick={() => setSelected(company)} aria-label={`${company.name}の根拠と記録を開く`}>
                    <strong>{company.name}</strong><small>{company.id}</small>
                  </button></span>
                  <span role="cell" className="mono">{company.ticker ?? '—'}</span>
                  <span role="cell" className="cell-muted">{company.sector ?? '未分類'}</span>
                  <span role="cell"><span className={`status-dot ${company.tier1FinancialRecordCount ? 'status-dot--source' : ''}`} title={company.tier1FinancialRecordCount ? '層1の財務記録あり。企業固有シミュレーションには未使用' : '層1の財務記録がこの抽出にはない'} />{company.tier1FinancialRecordCount ? '開示' : '—'}</span>
                </div>
              );
            })}
          </div>
          {list.length === 0 && <p className="empty-note">該当する企業がありません。検索語を短くするか、表記を変えてください。</p>}
        </div>
        </div>
      </div>
      <div className="directory-detail panel">
        {selected ? <EvidenceDetail company={selected} ownership={ownership} /> : (
          <div className="firm-empty"><span className="firm-empty__icon"><Building2 size={21} /></span><h3>企業を選択してください</h3><p>この一覧は取引ネットワークを意味しません。選択後、企業識別情報と公開・構造化された資本関係を確認できます。</p></div>
        )}
      </div>
    </section>
  );
}
