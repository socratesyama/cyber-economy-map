#!/usr/bin/env python3
"""UN Comtrade 公開API（キー不要）から日本中心の二国間貿易を取得.
JP-core設計: 日本の相手国別 輸出/輸入総額 + エネルギー(HS27)・機電(HS84/85)の輸入内訳。
二次波及（他国間の貿易停止）はLayer A(ICIO)が担うため、Comtradeは日本分のみで十分。"""
import csv, json, time, urllib.request, urllib.parse

BASE = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
# M49 numeric -> ISO3 (主要国)
M49 = {4:"AFG",8:"ALB",12:"DZA",24:"AGO",32:"ARG",36:"AUS",40:"AUT",44:"BHS",48:"BGD",50:"BGD",
 51:"ARM",56:"BEL",64:"BTN",68:"BOL",70:"BIH",72:"BWA",76:"BRA",96:"BRN",100:"BGR",104:"MMR",
 108:"BDI",112:"BLR",116:"KHM",120:"CMR",124:"CAN",132:"CPV",140:"CAF",144:"LKA",148:"TCD",
 152:"CHL",156:"CHN",158:"TWN",170:"COL",178:"COG",180:"COD",188:"CRI",191:"HRV",192:"CUB",
 196:"CYP",203:"CZE",204:"BEN",208:"DNK",212:"DMA",214:"DOM",218:"ECU",222:"SLV",226:"GNQ",
 231:"ETH",232:"ERI",233:"EST",242:"FJI",246:"FIN",250:"FRA",262:"DJI",266:"GAB",268:"GEO",
 270:"GMB",275:"PSE",276:"DEU",288:"GHA",292:"GIB",296:"KIR",300:"GRC",304:"GRL",308:"GRD",
 320:"GTM",324:"GIN",328:"GUY",332:"HTI",340:"HND",344:"HKG",348:"HUN",352:"ISL",356:"IND",
 360:"IDN",364:"IRN",368:"IRQ",372:"IRL",376:"ISR",380:"ITA",384:"CIV",388:"JAM",392:"JPN",
 398:"KAZ",400:"JOR",404:"KEN",408:"PRK",410:"KOR",414:"KWT",417:"KGZ",418:"LAO",422:"LBN",
 426:"LSO",428:"LVA",430:"LBR",434:"LBY",440:"LTU",442:"LUX",446:"MAC",450:"MDG",454:"MWI",
 458:"MYS",466:"MLI",470:"MLT",478:"MRT",484:"MEX",492:"MCO",496:"MNG",498:"MDA",499:"MNE",
 500:"MSR",504:"MAR",508:"MOZ",512:"OMN",516:"NAM",524:"NPL",528:"NLD",540:"NCL",548:"VUT",
 554:"NZL",558:"NIC",562:"NRO",566:"NGA",578:"NOR",583:"FSM",586:"PAK",591:"PAN",598:"PNG",
 600:"PRY",604:"PER",608:"PHL",616:"POL",620:"PRT",624:"GNB",626:"TLS",630:"PRI",634:"QAT",
 642:"ROU",643:"RUS",646:"RWA",682:"SAU",686:"SEN",688:"SRB",690:"SYC",694:"SLE",702:"SGP",
 703:"SVK",704:"VNM",705:"SVN",706:"SOM",710:"ZAF",716:"ZWE",724:"ESP",728:"SSD",729:"SDN",
 740:"SUR",748:"SWZ",752:"SWE",756:"CHE",760:"SYR",762:"TJK",764:"THA",768:"TGO",780:"TTO",
 784:"ARE",788:"TUN",792:"TUR",795:"TKM",798:"TUV",800:"UGA",804:"UKR",807:"MKD",818:"EGY",
 826:"GBR",834:"TZA",840:"USA",850:"USV",854:"BFA",858:"URY",860:"UZB",862:"VEN",882:"WST",
 887:"YEM",894:"ZMB"}
PARTNERS = ",".join(str(c) for c in M49)

def q(cmd, flow, partners=PARTNERS, year=2023, reporter=392):
    params = {"reporterCode": reporter, "period": year, "partnerCode": partners,
              "cmdCode": cmd, "flowCode": flow, "maxRecords": 500}
    url = BASE + "?" + urllib.parse.urlencode(params)
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CyberEconomyMap/0.1"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r).get("data", [])
        except Exception as e:
            print("  retry", attempt, str(e)[:60]); time.sleep(20)
    return []

def main():
    jobs = [("TOTAL", "X"), ("TOTAL", "M"), ("27", "M"), ("85", "M"), ("84", "M"), ("27", "X")]
    rows = []
    for cmd, flow in jobs:
        print(f"JPN flow={flow} HS={cmd} ...", flush=True)
        data = q(cmd, flow)
        n = 0
        for d in data:
            iso = M49.get(d.get("partnerCode"))
            if not iso: continue
            val = d.get("primaryValue") or 0
            rows.append({"year": d.get("refYear"), "reporter": "JPN", "flow": flow,
                         "hs": cmd, "partner": iso, "value_usd": val})
            n += 1
        print("  records:", n, flush=True)
        time.sleep(10)
    with open("data/comtrade_bilateral.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["year", "reporter", "flow", "hs", "partner", "value_usd"])
        w.writeheader(); w.writerows(rows)
    print("TOTAL rows:", len(rows))

if __name__ == "__main__":
    main()
