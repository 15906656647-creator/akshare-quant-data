# Stage 17.6.2 涓滄柟璐㈠瘜娓偂鎺ュ彛閲嶆柊楠岃瘉

楠岃瘉鎵规锛歚f041b62c-ea95-4f37-a9d5-6b0d9d4a27d8`
涓氬姟鍩哄噯鏃ワ細`2026-08-24`
Provider锛歚eastmoney`
Interface锛歚stock_hk_hist`

## 缁撹

- Provider楠岃瘉鐘舵€侊細`BLOCKED`锛?/21 PASS锛夈€?
- Stage 17姝ｅ紡鐘舵€佷粛涓猴細`BLOCKED`銆?
- Stage 18鎺堟潈锛歚false`銆?
- 鏈壒鍙獙璇佷笢鏂硅储瀵屽€欓€夛紝涓嶅缓璁綪rovider Registry銆佷笉閲嶈窇姝ｅ紡Stage 17銆?

| symbol | adjust | status | rows | first_date | coverage | issue |
| --- | --- | --- | ---: | --- | --- | --- |
| 02180.HK | raw | FAIL | 1314 | 2019-07-10 | complete_to_verified_listing_date | ohlc_logic_error |
| 02180.HK | qfq | FAIL | 1314 | 2019-07-10 | complete_to_verified_listing_date | ohlc_logic_error |
| 02180.HK | hfq | FAIL | 1314 | 2019-07-10 | complete_to_verified_listing_date | ohlc_logic_error |
| 08365.HK | raw | PASS | 1780 | 2017-05-26 | complete_to_verified_listing_date | - |
| 08365.HK | qfq | PASS | 1780 | 2017-05-26 | complete_to_verified_listing_date | - |
| 08365.HK | hfq | PASS | 1780 | 2017-05-26 | complete_to_verified_listing_date | - |
| 08462.HK | raw | PASS | 1800 | 2017-07-17 | complete_to_verified_listing_date | - |
| 08462.HK | qfq | PASS | 1800 | 2017-07-17 | complete_to_verified_listing_date | - |
| 08462.HK | hfq | PASS | 1800 | 2017-07-17 | complete_to_verified_listing_date | - |
| 02076.HK | raw | FAIL | 708 | 2022-12-22 | complete_to_verified_listing_date | ohlc_logic_error |
| 02076.HK | qfq | FAIL | 708 | 2022-12-22 | complete_to_verified_listing_date | ohlc_logic_error |
| 02076.HK | hfq | FAIL | 708 | 2022-12-22 | complete_to_verified_listing_date | ohlc_logic_error |
| 06100.HK | raw | FAIL | 2004 | 2018-06-29 | complete_to_verified_listing_date | ohlc_logic_error |
| 06100.HK | qfq | FAIL | 2004 | 2018-06-29 | complete_to_verified_listing_date | ohlc_logic_error |
| 06100.HK | hfq | FAIL | 2004 | 2018-06-29 | complete_to_verified_listing_date | ohlc_logic_error |
| 06919.HK | raw | FAIL | 1445 | 2019-12-13 | complete_to_verified_listing_date | ohlc_logic_error |
| 06919.HK | qfq | FAIL | 1445 | 2019-12-13 | complete_to_verified_listing_date | ohlc_logic_error |
| 06919.HK | hfq | FAIL | 1445 | 2019-12-13 | complete_to_verified_listing_date | ohlc_logic_error |
| 09669.HK | raw | FAIL | 825 | 2023-04-13 | complete_to_verified_listing_date | ohlc_logic_error |
| 09669.HK | qfq | FAIL | 825 | 2023-04-13 | complete_to_verified_listing_date | ohlc_logic_error |
| 09669.HK | hfq | FAIL | 825 | 2023-04-13 | complete_to_verified_listing_date | ohlc_logic_error |

## 鍒ゅ畾瑙勫垯

姣忛」蹇呴』鍚屾椂婊¤冻闈炵┖銆丱HLC鍖呯粶鍚堟硶銆佹垚浜ら噺闈炶礋銆佹棩鏈熼€掑涓斿敮涓€銆佹棤鏈潵鏃ユ湡锛屼互鍙?
`complete_to_verified_listing_date`銆傝繛鎺ュけ璐ャ€佺┖缁撴灉銆丼chema閿欒鍜岃川閲忛敊璇垎鍒褰曪紱
涓嬭浇鎴愬姛涓嶇瓑浜庤川閲忛€氳繃銆?

鍘熷AKShare DataFrame鍜屽彧鏀瑰垪鍚嶇殑瑙勮寖鍊欓€夊垎鍒拷鍔犱繚瀛樸€傞獙璇佽繃绋嬩笉淇敼OHLC銆佷笉鎻掑€笺€?
涓嶅垹闄ゅ紓甯告棩鏈燂紝涔熶笉浣跨敤raw鏇夸唬qfq/hfq銆?

## 涓嬩竴闂ㄧ

鍗充娇涓滄柟璐㈠瘜21/21閫氳繃锛屼篃鍙叿澶囪繘鍏ュ悗缁璓rovider Registry浠诲姟鐨勮祫鏍笺€傛湰鎵逛笉鏄?9椤?
A/H鏃ョ嚎涓?椤笶TH鐨勬寮忛噸璺戯紝涓嶈兘鎶奡tage 17鏀逛负PASS锛屼篃涓嶈兘鎺堟潈Stage 18銆?
