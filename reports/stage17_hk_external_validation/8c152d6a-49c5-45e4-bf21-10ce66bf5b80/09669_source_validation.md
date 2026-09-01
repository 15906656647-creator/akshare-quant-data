# Stage 17.6.3锛?9669.HK 澶栭儴鏁版嵁婧愪笓椤归獙璇?

楠岃瘉鎵规锛歚8c152d6a-49c5-45e4-bf21-10ce66bf5b80`
涓氬姟鍩哄噯鏃ワ細`2026-08-24`

## 缁撹

- 涓撻」鐘舵€侊細`BLOCKED`銆?
- Stage 17姝ｅ紡鐘舵€佷粛涓猴細`BLOCKED`锛汼tage 18鎺堟潈锛歚false`銆?
- 鏈壒鏈缓璁綪rovider Registry锛屾湭閲嶈窇姝ｅ紡Stage 17銆?
- 鏃㈡湁涓夋簮璇佹嵁琛ㄦ槑鑵捐raw閫氳繃浣唓fq/hfq鎺ュ彛澶辫触锛涙柊娴拰涓滄柟璐㈠瘜鐨?9669鍊欓€夊瓨鍦∣HLC寮傚父銆?

## 璺ㄦ簮鍚屾寮傚父

- `hfq` `2024-03-07`锛歟astmoney, sina
- `qfq` `2024-03-07`锛歟astmoney, sina
- `raw` `2024-03-07`锛歟astmoney, sina, yahoo

瀹屾暣寮傚父琛屻€佹帴鍙ｅけ璐ュ崰浣嶈鍜屾棦鏈塕aw鍝堝笇瑙乣09669_provider_comparison.csv`銆傛瘮杈冭繃绋嬪彧璇诲苟
鏍￠獙鏃㈡湁Raw锛屼笉閲嶅啓銆佷笉鍒犻櫎銆佷笉鎻掑€硷紝涔熶笉鎶妑aw褰撲綔澶嶆潈琛屾儏銆?

## 澶栭儴鏉ユ簮缁撴灉

| provider | requested_adjust | status | quality | provider semantics | reason |
| --- | --- | --- | --- | --- | --- |
| yahoo | raw | FAIL | FAIL | provider_native_raw_ohlc_and_adjusted_close_only | ohlc_logic_error |
| yahoo | qfq | FAIL | NOT_RUN | provider_native_raw_ohlc_and_adjusted_close_only | adjusted_close_is_not_verified_qfq_ohlc |
| yahoo | hfq | FAIL | NOT_RUN | provider_native_raw_ohlc_and_adjusted_close_only | adjusted_close_is_not_verified_hfq_ohlc |
| alpha_vantage | capability | UNAVAILABLE | NOT_RUN | provider_adjusted_daily_not_assumed_qfq_or_hfq | api_key_not_configured; no request sent |
| hkex | capability | UNAVAILABLE | NOT_RUN | no licensed adjusted-history interface configured | product entitlement and interface not configured; no request sent |

Yahoo鐨刞Adj Close`浠呮槸Provider鍘熺敓璋冩暣鏀剁洏搴忓垪锛屼笉鍖呭惈璋冩暣鍚庣殑瀹屾暣OHLC锛屼篃娌℃湁璇佹嵁鍙?
璇佹槑鍏跺悓鏃剁瓑浠蜂簬鏈」鐩殑鍓嶅鏉冨拰鍚庡鏉冦€傚洜姝ゅ嵆浣縔ahoo raw OHLC閫氳繃锛屼篃涓嶈兘鐢ㄤ簬鍐掑厖
`qfq/hfq`銆侫lpha Vantage娌℃湁閰嶇疆API瀵嗛挜鏃朵笉鍙戣捣璇锋眰锛汬KEX鏈厤缃巿鏉冩暟鎹骇鍝佹椂涓嶅皢
鍏紑缃戦〉鎴栨帹鏂€煎啋鍏呭巻鍙插鏉冩暟鎹€?

## 鍚庣画闂ㄧ

鍙湁鍙璁℃潵婧愪负`09669.HK`鍚屾椂鎻愪緵鍚堟硶raw銆乹fq銆乭fq瀹屾暣OHLC骞惰鐩栧凡鏍搁獙涓婂競鏃ユ湡锛?
鎵嶅叿澶囪繘鍏ョ嫭绔婸rovider Registry浠诲姟鐨勬潯浠躲€傚惁鍒欏簲淇濇寔Stage 17 `BLOCKED`锛屾垨鍙﹁鎵ц
Stage 17.6.4鑼冨洿璋冩暣娌荤悊璇勪及锛涙湰浠诲姟涓嶄綔鑼冨洿璋冩暣銆?
