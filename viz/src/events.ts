export interface EventSpec {
  id: string;
  label: string;
  shortLabel: string;
  family: 'price' | 'logistics' | 'finance' | 'production' | 'policy' | 'hazard' | 'digital' | 'health' | 'trade';
  support: 'conditional' | 'proxy-only' | 'unavailable';
  supportedChannel: 'input-cost' | 'production-outage' | null;
  method: string;
  boundary: string;
  sourceKind: string;
}

export const EVENTS: EventSpec[] = [
  {
    id: 'oil-x2', label: '原油価格 2 倍', shortLabel: '原油価格 ×2', family: 'price', support: 'proxy-only',
    supportedChannel: 'input-cost', method: 'ICIO 2020の上流・エネルギー産業を入力ノードにした、投入係数ベースの費用圧力スイープ。',
    boundary: 'ICIO分類B05_06は石炭・原油・天然ガスをまとめる。原油だけの価格・契約・マージン・価格転嫁率は観測していない。出力は条件付き費用圧力proxyで、企業利益や売上の推計ではない。',
    sourceKind: '国×産業投入係数・利用者指定価格倍率・利用者指定の全額転嫁感度レンジ',
  },
  {
    id: 'taiwan-strait', label: '台湾海峡封鎖', shortLabel: '海峡封鎖', family: 'logistics', support: 'unavailable',
    supportedChannel: null, method: '正確な回廊・貿易フロー・産業露出がそろうまで封鎖固有の連鎖を算定しない。',
    boundary: '海運路データは航路名と集計値のみ。座標線、回廊経由の輸入、企業別輸送依存度は無い。別途、利用者が指定した台湾の国×産業生産ショックproxyとしてだけ計算可能。',
    sourceKind: '海峡経由の貿易経路連結なし',
  },
  {
    id: 'suez-stop', label: 'スエズ運河停止', shortLabel: 'スエズ停止', family: 'logistics', support: 'unavailable',
    supportedChannel: null, method: '経路×貿易フロー対応が無いため、所要日数・運賃・欠品を推計しない。',
    boundary: '集計的な経路レコードはあるが、製品・荷主・港湾・産業別の通過フローと迂回代替は無い。',
    sourceKind: '航路の集計メタデータのみ。経路別露出データなし',
  },
  {
    id: 'bank-failure', label: '大手銀行破綻', shortLabel: '銀行破綻', family: 'finance', support: 'unavailable',
    supportedChannel: null, method: '銀行間与信、貸出先、預金者、資金調達関係の観測が無いため、信用・流動性波及を算定しない。',
    boundary: '資本関係を貸出・債権・与信枠の代わりに使わない。金融部門IOは個別銀行デフォルト損失ではない。',
    sourceKind: '与信ネットワークおよび債権データなし',
  },
  {
    id: 'fab-stop', label: '半導体工場停止', shortLabel: '工場停止', family: 'production', support: 'proxy-only',
    supportedChannel: 'production-outage', method: '利用者が指定した産業中断を、IOの国×産業構造を経由させる条件付き供給ショック。',
    boundary: '工場の正確な位置・生産能力・稼働率と個別半導体企業は収録していない。C26はコンピュータ・電子製品の広い集計分類で、半導体工場専用分類ではない。',
    sourceKind: '利用者が指定した国×産業・中断幅・代替率・在庫仮定',
  },
  {
    id: 'sanctions', label: '特定国への制裁', shortLabel: '国制裁', family: 'policy', support: 'proxy-only',
    supportedChannel: 'production-outage', method: '利用者指定の対象国×産業ショックproxyとしてのみ解析可能。制裁リストの法的対象や迂回を判定しない。',
    boundary: '有効な制裁制度と企業・品目・時点別対象者マッピング、二次制裁・迂回輸出データは無い。',
    sourceKind: '利用者指定の国・産業・中断条件',
  },
  {
    id: 'earthquake', label: '大地震', shortLabel: '地震', family: 'hazard', support: 'proxy-only',
    supportedChannel: 'production-outage', method: '工場位置データがある場合のみ物理的被害を接続する設計。現スナップショットでは利用者指定の国×産業停止proxyに限定。',
    boundary: '地震ハザード形状、工場座標、建物脆弱性、地域内輸送設備の露出データが無い。',
    sourceKind: '利用者が指定した地域・産業・直接ショック幅',
  },
  {
    id: 'port-closure', label: '港湾閉鎖', shortLabel: '港湾閉鎖', family: 'logistics', support: 'unavailable',
    supportedChannel: null, method: '位置情報と収録貨物・産業のリンクが無いため、生産損失や到達時間を計算しない。',
    boundary: '現DBの港は6点であり、企業・産業・貿易フローと結ばれていない。',
    sourceKind: '一部港湾の座標のみ。港別露出データなし',
  },
  {
    id: 'cyber-attack', label: 'サイバー攻撃', shortLabel: 'サイバー攻撃', family: 'digital', support: 'proxy-only',
    supportedChannel: 'production-outage', method: '利用者指定の会社／産業中断幅がある場合に、その産業proxyへのIO波及だけ解析できる。',
    boundary: 'ITシステム依存、委託先、侵害、復旧時間、個社の生産シェアの観測が無い。',
    sourceKind: '利用者指定の直接影響先と産出中断条件',
  },
  {
    id: 'pandemic', label: 'パンデミック', shortLabel: 'パンデミック', family: 'health', support: 'proxy-only',
    supportedChannel: 'production-outage', method: '利用者指定の国×産業供給側中断proxyの範囲でのみ計算できる。感染者数・行動制限・需要ショックは未接続。',
    boundary: '疾病伝播、労働力欠損、国別規制、需要・価格弾力性データが無い。',
    sourceKind: '利用者指定の国×産業・供給中断条件',
  },
  {
    id: 'export-ban', label: '特定原材料の輸出禁止', shortLabel: '資源輸出禁止', family: 'trade', support: 'proxy-only',
    supportedChannel: 'production-outage', method: '輸出禁止国の利用者指定産業を供給側入力にした産業連関proxyとしてのみ実行可能。',
    boundary: 'HS品目×国×企業の取引先対応が無く、品目の輸出停止、在庫、免除・迂回を直接は計算しない。',
    sourceKind: '利用者指定の供給国×産業・停止範囲',
  },
];

export const DEFAULT_EVENT_ID = 'oil-x2';
