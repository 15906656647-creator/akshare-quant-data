# Stage 17.6.1 鑵捐娓偂鎺ュ彛楠岃瘉

> 楠岃瘉鎵规锛歚a7c3e6d1-90b4-4c15-a268-4c5c4bc66ba2`
> 涓氬姟鍩哄噯鏃ワ細`2026-08-24`
> Provider锛歚tencent`
> Interface锛歚stock_zh_ah_daily`

## 缁撹

- Provider楠岃瘉鐘舵€侊細`BLOCKED`锛?7/21 PASS锛夈€?
- Stage 17姝ｅ紡鐘舵€佷粛涓猴細`BLOCKED`銆?
- Stage 18鎺堟潈锛歚false`銆?
- 鏈壒鍙獙璇佽吘璁€欓€夛紝涓嶆嫾鎺ユ棫Raw銆佷笉鏇挎崲姝ｅ紡69椤广€佷笉閲嶈窇Stage 17銆?

| symbol | adjust | status | rows | first_date | coverage | issue |
| --- | --- | --- | ---: | --- | --- | --- |
| 02180.HK | raw | PASS | 1757 | 2019-07-10 | complete_to_verified_listing_date | - |
| 02180.HK | qfq | PASS | 1757 | 2019-07-10 | complete_to_verified_listing_date | - |
| 02180.HK | hfq | PASS | 1757 | 2019-07-10 | complete_to_verified_listing_date | - |
| 08365.HK | raw | PASS | 2278 | 2017-05-26 | complete_to_verified_listing_date | - |
| 08365.HK | qfq | PASS | 2278 | 2017-05-26 | complete_to_verified_listing_date | - |
| 08365.HK | hfq | PASS | 2278 | 2017-05-26 | complete_to_verified_listing_date | - |
| 08462.HK | raw | PASS | 2243 | 2017-07-17 | complete_to_verified_listing_date | - |
| 08462.HK | qfq | FAIL | 0 | - | history_unavailable | upstream_error |
| 08462.HK | hfq | FAIL | 0 | - | history_unavailable | upstream_error |
| 02076.HK | raw | PASS | 900 | 2022-12-22 | complete_to_verified_listing_date | - |
| 02076.HK | qfq | PASS | 900 | 2022-12-22 | complete_to_verified_listing_date | - |
| 02076.HK | hfq | PASS | 900 | 2022-12-22 | complete_to_verified_listing_date | - |
| 06100.HK | raw | PASS | 2008 | 2018-06-29 | complete_to_verified_listing_date | - |
| 06100.HK | qfq | PASS | 2008 | 2018-06-29 | complete_to_verified_listing_date | - |
| 06100.HK | hfq | PASS | 2008 | 2018-06-29 | complete_to_verified_listing_date | - |
| 06919.HK | raw | PASS | 1647 | 2019-12-13 | complete_to_verified_listing_date | - |
| 06919.HK | qfq | PASS | 1647 | 2019-12-13 | complete_to_verified_listing_date | - |
| 06919.HK | hfq | PASS | 1647 | 2019-12-13 | complete_to_verified_listing_date | - |
| 09669.HK | raw | PASS | 829 | 2023-04-13 | complete_to_verified_listing_date | - |
| 09669.HK | qfq | FAIL | 0 | - | history_unavailable | upstream_error |
| 09669.HK | hfq | FAIL | 0 | - | history_unavailable | upstream_error |

## 鍒ゅ畾瑙勫垯

姣忛」蹇呴』鍚屾椂婊¤冻锛氶潪绌恒€佹棩鏈熼€掑涓斿敮涓€銆佹棤鏈潵鏃ユ湡銆丱HLC鍖呯粶鍚堟硶銆佹垚浜ら噺闈炶礋锛屼互鍙?
鏈€鏃╄褰曡鐩栧埌宸叉湁涓婂競鏃ユ湡璇佹嵁瀵瑰簲鐨勯涓氦鏄撳尯闂淬€備笅杞芥垚鍔熶笉绛変簬璐ㄩ噺閫氳繃銆?

AKShare鎺ュ彛鎸夌浉閭诲勾浠戒骇鐢熼噸鍙犲搷搴旀椂锛屼粎鍏佽鍒犻櫎鎵€鏈夊瓧娈靛畬鍏ㄧ浉鍚岀殑閲嶅鏃ユ湡锛屽苟鍚屾椂
淇濆瓨鏈幓閲峘source_response`鍜屽幓閲嶆暟閲忥紱鍚屾棩鍊煎啿绐佹椂鐩存帴澶辫触銆備换浣曚环鏍煎€煎潎涓嶄慨鏀广€?
涓嶆彃鍊笺€佷笉鎴柇寮傚父琛屻€?

## 涓嬩竴闂ㄧ

鍗充娇鑵捐21/21閫氳繃锛屼篃鍙兘璇存槑璇ュ€欓€夊叿澶囪繘鍏ユ寮廠tage 17瀹屾暣鏂版壒娆＄殑璧勬牸銆傚繀椤诲彟琛?
浣跨敤鍏ㄦ柊run_id瀹屾暣閲嶈窇69椤笰/H鏃ョ嚎銆?椤笶TH鍙婃竻鍗曡鐩栭棬绂侊紝姝ｅ紡Stage 17杈惧埌`PASS`
鍚庢墠鑳芥巿鏉僑tage 18銆傛湰浠诲姟涓嶆墽琛岃閲嶈窇銆?
