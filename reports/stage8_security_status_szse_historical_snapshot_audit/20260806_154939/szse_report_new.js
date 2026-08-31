<!DOCTYPE html>
<html lang="zh-cmn-Hans">
<head>
    <meta charset="utf-8">
<!--   <title>深交所主页</title>   -->
<script>
    var title = '<a href="./" class="CurrChnlCls">404</a> ';
    title = title.substring(title.indexOf('>')+1,title.indexOf('</'));
    document.write('<title>深圳证券交易所-'+ title +'</title>')
</script>
<script>
  if(location.protocol == 'https:'){
    document.write('<link href="https://res.szse.cn/common/images/favicon.ico" rel="shortcut icon" type="image/x-icon" />');
  }else{
    document.write('<link href="http://res.static.szse.cn/common/images/favicon.ico" rel="shortcut icon" type="image/x-icon" />');
  }
</script>
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1, user-scalable=0" />
<meta http-equiv="cache-control" content="max-age=0">
<meta http-equiv="cache-control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="expires" content="0">
<meta http-equiv="expires" content="Web, 26 Feb 1997 08:21:57 GMT">
<meta http-equiv="pragma" content="no-cache">
<meta name="author" content="www.szse.cn">
<meta name="description" content="深交所官网">
<meta name="keywords" content="深交所,深交所官网,深圳证券交易所,交易所,交易所官网,深圳证券交易所官网">
<meta name="renderer" content=webkit>
<meta name="X-UA-Compatible" content="IE=edge">
<meta name="google" value="notranslate"> 
<meta name="format-detection" content="telephone=no">
<meta name="format-detection" content="email=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black">
<meta name="screen-orientation" content="portrait">
<meta name="full-screen" content="yes">
<meta name="browermode" content="application">
<meta name="x5-orientation" content="portrait">
<meta name="HandheldFriendly" content="true">
<script type="text/javascript">
	var u = navigator.userAgent;
	var isAndroid = u.indexOf('Android') > -1 || u.indexOf('Adr') > -1;//android终端

	function addElementMeta(name,  content) {
		var head = document.getElementsByTagName('head')[0];
		var meta = document.createElement('meta');

		meta.setAttribute('name', name);
		meta.setAttribute('content', content);
		head.appendChild(meta);
	}
	if(isAndroid) {
		addElementMeta('x5-fullscreen', 'true');
		addElementMeta('x5-page-mode', 'app');
	}
</script> 
    <script>
  (function () {
    var _versionDate = new Date().getTime();
    if (location.protocol == 'https:') {
      var _path = 'https://res.szse.cn';
    } else {
      var _path = 'http://res.static.szse.cn';
    }
    // _path = _path.replace(".static.", ".");
    //var _path = 'http://res.szse.cn';
    //document.write( " <script src='" + _path + "/common/js/first.js?random=" + _versionDate + "'> <\/script> ");
    var _host = 'http://www.szse.cn';
    if (location.protocol == 'https:') {
      _host = 'https://www.szse.cn';
    }


    var backDomain = 'http://www.sse.org.cn'
    var reg = /([a-zA-Z0-9][-a-zA-Z0-9]{0,62})((\.[a-zA-Z0-9][-a-zA-Z0-9]{0,62})+)\.?(:\d+)?/;
    if (backDomain && window.location.host.match(reg)[2] === backDomain.match(reg)[2]) {
      _host = 'http://www.sse.org.cn';
      _path = 'http://res.static.sse.org.cn';
      if (location.protocol == 'https:') {
        _host = 'https://www.sse.org.cn';
        _path = 'https://res.static.sse.org.cn';
      }

    }

    _path = _path.replace(".static.", ".");

    document.write(" <script src='" + _host + "/szsePath.js?random=" + _versionDate + "'> <\/script> "
      + " <script src='" + _path + "/common/js/concatversion.js?random=" + _versionDate + "'> <\/script> ");
  }());
</script>

<script>

  function backDomainLinkSwitch(value, type) {
    var _port = location.port ? (":" + location.port) : "";
    var reg = /([a-zA-Z0-9][-a-zA-Z0-9]{0,62})((\.[a-zA-Z0-9][-a-zA-Z0-9]{0,62})+)\.?(:\d+)?/;
    var urlRegx = /(.*)(http:|https:)(\/\/)(([a-zA-Z0-9][-a-zA-Z0-9]{0,62})((\.[a-zA-Z0-9][-a-zA-Z0-9]{0,62})+))\.?(:\d+)?(.*)/;

    // html字符串替换
    if (type == 'str') {
      var strArr = value.split("=");
      strArr = strArr.map(function (v) {
        var host = reg.test(v) ? v.match(reg)[0] : null;
        if (pathObj.szseHosts.indexOf(host) > -1) {
          if (window.location.protocol == 'https:' && urlRegx.test(v)) {
            v = v.replace(urlRegx, '$1https:$3$4' + _port + '$9');
          };
          if (pathObj.current_host === pathObj.back_host) {
            v = v.replace(pathObj.main_host, pathObj.back_host);
          }
        }
        return v
      });
      value = strArr.join("=");
      return value;
    }

    // a标签地址替换
    if (type === 'A') {
      var eleA = document.querySelectorAll(value);
      for (var i = 0; i < eleA.length; i++) {
        var href = eleA[i].getAttribute("href");
        var host = reg.test(href) ? href.match(reg)[0] : null;
        if (href && pathObj.szseHosts.indexOf(host) > -1) {
          if (window.location.protocol == 'https:') {
            href = href.replace(urlRegx, '$1https:$3$4' + _port + '$9');
          };
          if (pathObj.current_host === pathObj.back_host) {
            href = href.replace(pathObj.main_host, pathObj.back_host);
          }
          eleA[i].setAttribute('href', href);
        }
      }
    }

    // 单链接替换
    if (type === "link") {
      if (window.location.protocol == 'https:' && !!value) {
        value = value.replace(urlRegx, '$1https:$3$4' + _port + '$9');
      };
      if (pathObj.current_host === pathObj.back_host) {
        var host = reg.test(value) ? value.match(reg)[0] : null;
        if (value && pathObj.szseHosts.indexOf(host) > -1) {
          value = value.replace(pathObj.main_host, pathObj.back_host);
        }
      }
      return value;
    }

    // 背景图地址更换
    if (type === "background") {
      var eleBg = document.querySelectorAll(value);
      for (var i = 0; i < eleBg.length; i++) {
        var href = eleBg[i].style.backgroundImage;
        if (window.location.protocol == 'https:' && !!href) {
          href = href.replace(urlRegx, '$1https:$3$4' + _port + '$9');
        };
        var host = reg.test(href) ? href.match(reg)[0] : null;
        if (href && pathObj.szseHosts.indexOf(host) > -1) {
          if (pathObj.current_host === pathObj.back_host) {
            href = href.replace(pathObj.main_host, pathObj.back_host);
          }
          eleBg[i].style.backgroundImage = href;
        }
      }
    }

  }

</script>

<script>
   if(document.cookie.indexOf('ft_language=1')>-1){
    var style = document.createElement('style');
    style.textContent='body{visibility:hidden;}';
    document.head.appendChild(style);
  }
</script>
<script>
    addComCssFile()
</script>
    <style>
        @media (max-width: 768px) {
            .error-pic{width:100%;}
            .error-info{font-size:20px!important;}
        }
    </style>
</head>
  <body>
    <script>
  navMenuAJAX('/application/publicindex/header/index.html', '/application/publicindex/header/index.html', 'header', 'www');
</script>
  
    <div class="g-container-wrap mt50">
<div class="g-container">
<div class="g-conbox">
<p class="text-center error-wrap"><img class="error-pic" alt="" src="http://res.static.szse.cn/common/images/page_notFound_1.png" /></p>
<!-- <p class="text-center">    <span class="error-number">404</span><br /> 
<span class="error-info" style="font-size:24px;color:#999;">抱歉，你所访问的页面不存在！</span><br />
<span class="error-body" style="color:#bbb;">你所查看的网页可能被删除或者暂时不可用</span><br />
<span class="error-body" style="color:#bbb;">点击以下链接继续浏览网站</span>
</p> -->
<p style="margin-top:95px;">
<img class="" alt="" src="http://res.static.szse.cn/common/images/home_page.png" />
<a class="szse_index" style="margin-left: 6px;text-decoration: underline;color: #666666;cursor: pointer;">返回首页</a>
<!--<img class="" alt="" src="http://res.static.szse.cn/common/images/go_back.png" style="margin-left:44px;" />
<a class="goBack" style="margin-left: 6px;text-decoration: underline;color: #666666;cursor: pointer;">返回上一页</a> -->
</p>
</div>
</div>
</div>

    <script>
  changeVertion('/common/js/toggleBig5.js', 'js');
  navMenuAJAX('/application/publicindex/footer/index.html','/application/publicindex/footer/index.html', 'footer','www');
  addComJsFile();
</script>
  </body>
<script>
     $('.szse_index').click(function(){
            window.location = pathObj.main_domain_path_http;
     });

     $('.goBack').click(function(){
            window.history.go(-1);
     });
</script>
</html>