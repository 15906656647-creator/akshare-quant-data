# Stage 17 娓偂OHLC鏍瑰洜涓庢浛浠ｆ潵婧愯瘎浼?

> 瀹¤鏃ユ湡锛?026-08-25
> 涓氬姟鍩哄噯鏃ワ細2026-08-24
> 琚璁℃寮忔壒娆★細`78cddc46-4b2a-4ebe-9065-1e54e3dff522`
> 闃舵鐘舵€侊細`BLOCKED`锛汼tage 18鎺堟潈锛歚false`

## 瀹¤鑼冨洿涓庣粨璁?

鏈姤鍛婂璁?鍙腐鑲＄殑鏈鏉冦€佸墠澶嶆潈銆佸悗澶嶆潈鏂版氮鍊欓€夛紝鍏?1涓暟鎹泦锛涒€?1鈥濅笉鏄?1鍙?
涓嶅悓鑲＄エ銆傚璁″厛鏍稿姝ｅ紡manifest鐧昏鐨?2涓€欓€塕aw/metadata鏂囦欢澶у皬涓嶴HA-256锛屽啀
閫愯澶嶇畻锛屼笉璁块棶缃戠粶銆佷笉淇敼Raw銆佷笉鍒犻櫎寮傚父琛屻€佷笉鎻掑€笺€?

21/21鏁版嵁闆嗗潎瀛樺湪OHLC鍖洪棿杩濊锛屽叡1,089鏉★細鏈鏉?11鏉°€佸墠澶嶆潈
339鏉°€佸悗澶嶆潈339鏉°€傛湭澶嶆潈鏁版嵁宸插紓甯革紱鍓?鍚庡鏉冪殑鎵€鏈夊紓甯告棩鏈熷潎鑳?
鍦ㄥ悓鏍囩殑鏈鏉冨紓甯告棩鏈熼泦鍚堜腑鎵惧埌銆傚洜姝ゅ綋鍓嶈瘉鎹敮鎸侊細

- 瀛楁鏄犲皠閿欒锛氭帓闄わ紱鏂囦欢宸叉槸绮剧‘鐨刞date/open/high/low/close/volume`瑙勮寖鍒椼€?
- 浠ｇ爜鏄犲皠閿欒锛氭帓闄わ紱`.HK`宸茬ǔ瀹氭槧灏勪负浜斾綅鏁板瓧锛屼笖鍚勫簭鍒楄捣鐐逛笌宸插璁′笂甯傛棩涓€鑷淬€?
- 椤圭洰澶嶆潈閫昏緫閿欒锛氫笉鏄牴鍥狅紱椤圭洰娌℃湁鑷澶嶆潈锛孉KShare瀵瑰洓涓环鏍煎瓧娈典娇鐢ㄥ悓涓€鍥犲瓙锛?
  鏈鏉冨紓甯稿湪澶嶆潈搴忓垪涓紶鎾€?
- 鏍瑰洜鍒嗙被锛歚upstream_raw_ohlc_inconsistency`锛屽鏉冨簭鍒楁爣璁颁负
  `upstream_raw_inconsistency_propagated_by_adjustment`銆?

鏃ユ湡瀹¤涓殑`weekday_gap_candidate_count`鍙〃绀鸿嚜鐒跺伐浣滄棩缂哄彛鍊欓€夛紱鏈帴鍏ユ潈濞佹腐鑲?
浜ゆ槗鏃ュ巻銆佸仠鐗屽拰涓婂競鐘舵€佸墠锛屼笉寰楁妸瀹冪洿鎺ユ弿杩颁负鈥滅己澶变氦鏄撴棩鈥濄€傞噸澶嶆棩鏈熴€佸懆鏈棩鏈熷拰
闈為€掑鏃ユ湡鍙﹁绮剧‘缁熻浜巂hk_dataset_summary.csv`銆?

## 鏇夸唬鏉ユ簮璇勪及

| 鍊欓€?| 褰撳墠璇佹嵁 | 鍐崇瓥 |
| --- | --- | --- |
| AKShare `stock_hk_hist`锛堜笢鏂硅储瀵岋級 | 瀹樻柟AKShare鏂囨。鏀寔娓偂鏃ョ嚎鍙婁笁绉嶅鏉冿紱鏈壒21娆″潎涓鸿繛鎺ュけ璐ワ紝骞堕潪璐ㄩ噺閫氳繃 | 淇濈暀涓绘簮锛涘厛鍋氱綉缁?鍩熷悕鍙揪鎬ч殧绂婚獙璇侊紝涓嶈兘鎶婇噸璇曟垚鍔熷綋浣滃巻鍙茶川閲忓凡閫氳繃 |
| AKShare `stock_hk_daily`锛堟柊娴級 | 鏈壒21/21璐ㄩ噺澶辫触锛汚KShare浠撳簱浜︽湁杩戞湡鎺ュ彛鏂伴矞搴﹂棶棰樿褰?| 浠呬繚鐣欎氦鍙夊璁¤瘉鎹紝涓嶅緱閫変负姝ｅ紡婧?|
| AKShare `stock_zh_ah_daily`锛堣吘璁級 | 褰撳墠瀹夎鐗堟湰瀛樺湪璇ュ巻鍙叉帴鍙ｅ苟鎺ュ彈raw/qfq/hfq锛屼絾鍚嶇О鍜屽疄鐜伴潰鍚慉+H鑼冨洿锛?鍙洰鏍囩殑閫傜敤鎬у皻鏈疄娴?| Stage 17涓嬩竴鐙珛淇浠诲姟鐨勯閫変綆鎴愭湰鍊欓€夛紱蹇呴』閫愭爣鐨勯獙璇佷唬鐮佽鐩栥€佸畬鏁村巻鍙层€丱HLC銆佸鏉冭韩浠藉拰瓒呮椂 |
| HKEX Historical Data / Data Marketplace | 娓氦鎵€绉板叾涓虹洿鎺ユ潵婧?鈥済olden source鈥濓紝鎻愪緵璇佸埜閫愮瑪鍘嗗彶浜у搧锛涢渶瑕佽闃呫€佽鍙拰浠庢垚浜ら噸寤烘棩绾?| 鏉冨▉鎬ф渶楂樼殑姝ｅ紡瑙ｉ樆璺嚎锛涘厛纭鎵€闇€骞翠唤銆佽鍙€佷氦浠樻牸寮忓拰鎴愭湰锛屽啀鍐冲畾鏄惁鎺ュ叆 |
| Alpha Vantage `TIME_SERIES_DAILY_ADJUSTED` | 瀹樻柟鏂囨。瑕嗙洊鍏ㄧ悆鑲＄エ銆?0骞翠互涓婏紝浣嗛娓唬鐮佽鐩栭渶鎼滅储楠岃瘉锛涙帴鍙ｇ粰鍘熷OHLC鍜岃皟鏁存敹鐩?鍏徃琛屽姩锛屼笉绛夊悓浜庝笁濂楀畬鏁碠HLC | 鍙仛鐙珛浜ゅ弶楠岃瘉鍊欓€夛紝涓嶈兘鏈粡7鍙唬鐮佸拰澶嶆潈璇箟楠岃瘉鐩存帴鏇夸唬69椤瑰彛寰?|
| Polygon Stocks | 瀹樻柟Stocks鏂囨。鏄庣‘鑱氱劍缇庡浗鑲＄エ甯傚満 | 涓嶉€傜敤浜庢湰娆℃腐鑲¤В闃?|
| Yahoo Finance / Stooq | 鏈鏈壘鍒版弧瓒虫寮忛獙鏀舵墍闇€鐨勫畼鏂圭ǔ瀹欰PI銆佹潵婧愬璁″拰涓夊鏉冭涔夎瘉鎹?| 鏆備笉杩涘叆姝ｅ紡鍊欓€夛紱鑻ヤ娇鐢ㄥ彧鑳藉厛瀹屾垚璁稿彲銆佹帴鍙ｇǔ瀹氭€у拰瀛楁璇箟涓撻」瀹¤ |

## 瀹樻柟璇佹嵁閾炬帴

- AKShare娓偂鎺ュ彛鏂囨。锛?https://github.com/akfamily/akshare/blob/main/docs/data/stock/stock.md>
- AKShare鏂版氮娓偂鎺ュ彛瀹炵幇锛?https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hk_sina.py>
- AKShare `stock_hk_daily`杩戞湡闂璁板綍锛?https://github.com/akfamily/akshare/issues/7133>
- HKEX Data Marketplace锛?https://www.hkex.com.hk/Services/Market-Data-Services/Historical-Data-Services/HKEX-Data-Marketplace?sc_lang=en>
- HKEX甯傚満鏁版嵁鑾峰彇璇存槑锛?https://www.hkex.com.hk/Global/Exchange/FAQ/Market-Data/Getting-Market-Data?sc_lang=en>
- Alpha Vantage瀹樻柟鏂囨。锛?https://www.alphavantage.co/documentation/>
- Polygon Stocks瀹樻柟瑕嗙洊璇存槑锛?https://polygon.io/docs/rest/stocks/overview>

## 鍚庣画闂ㄧ

鏈璁′笉鏂板鏁版嵁婧愰€傞厤鍣ㄣ€佷笉鑱旂綉閲囬泦銆佷笉閲嶈窇Stage 17锛屼篃涓嶆敼鍙樻寮忛獙鏀躲€備笅涓€浠诲姟搴?
鍏堥殧绂婚獙璇乣stock_zh_ah_daily`锛堣吘璁級鍜屼笢鏂硅储瀵岃繛鎺ワ紱濡傚潎涓嶈兘鎻愪緵7鍙腐鑲′笁绉嶅鏉冪殑
瀹屾暣鍚堟牸鍘嗗彶锛屽啀鎺ㄨ繘HKEX閲囪喘/鎺堟潈鎴栫粡鎵瑰噯鐨勪笓涓氭簮銆傚彧鏈夋柊鐨勫畬鏁存寮弐un鍚屾椂杈惧埌
69/69鏃ョ嚎銆?/6 ETH銆佷笂甯傝鐩栧拰娓呭崟鍝堝笇鍏ㄩ儴閫氳繃锛孲tage 17鎵嶅彲鏀逛负`PASS`骞舵巿鏉?
Stage 18銆?
