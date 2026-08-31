/**
 * 最新公告
 */
var LatestAnnouncement = {
  todayStr: get_systemDate_global(), //当前日期
  newDateTime: "",
  preTime: "", //暂存调用接口后的时间范围
  announceUrl:
    sseQueryURL + "security/stock/queryCompanyBulletinNew.do?jsonCallBack=?", //公告列表url
  announceParam: {
    //公告列表参数
    isPagination: true,
    "pageHelp.pageSize": 25,
    "pageHelp.cacheSize": 1,
    START_DATE: "", //开始日期
    END_DATE: "", //结束日期
    SECURITY_CODE: "", //证券代码
    TITLE: "", //关键字
    BULLETIN_TYPE: "", //公告类型
    stockType: "", // 1 =主板 ， 2=科创板，默认全部
  },
  flag_param: false, //公告参数是否变化
  toBoolean: true, //是否调用接口
  selectTypeNum: 0, //默认市场类型：全部
  announceFileUrl: "/disclosure/listedinfo/announcement/json/", //静态数据url
  announceSortFile: "stock_bulletin_publish_order.json", //排序
  announceCodeParam: {
    sortType: 1, //静态数据代码排序
  },
  announceNumUrl: sseQueryURL + "commonQuery.do?jsonCallBack=?", //公司，公告条数url
  announceNumParam: {
    //公司，公告条数参数
    sqlId: "COMMON_PL_SSGSXX_ZXGG_NUM_L",
    START_DATE: "",
    END_DATE: "",
    SECURITY_CODE: "",
    TITLE: "",
    BULLETIN_TYPE: "",
    MAX_DATE: 1,
    type: "inParams",
  },
  announceTypeUrl: "announce_type.json", //公告类型json文件
  gsjcs: {},
  hasDelMain:false,//主公告显示状态 true为只显示主公告 false为主次皆显示
  init: function () {
    LatestAnnouncement.getTypeList();
    LatestAnnouncement.loadEvents();
    LatestAnnouncement.getCodeSort();
    LatestAnnouncement.getNumAnnounce(1);
  },
  //默认方法及点击事件
  loadEvents: function () {
    // //添加‘只看公告正文’选框
    $('.announceLine').html('<div class="announceTypeList"><div class="announceDiv"><div class="big-type-title"><span class="iconfont iconcircle" name="hasDelMain"></span><b class="btype-name">只看公告正文</b></div></div></div>') 
    //栏目标题
    $(".js_announceTitle").html($(".js_page-title").text());
    //加载日历插件
    laydate({
      elem: ".js_laydateSearch",
      theme: "#b50005",
      format: "yyyy/MM/dd",
      range: true,
      trigger: "click",
      btns: ["confirm"],
      extrabtns: [
        { id: "today", 
          text: "今日", 
          range: latestType('today') },
        {
          id: "tomorrow",
          text: "明日",
          range: latestType('tomorrow')
        },
        {
          id: "latestThree",
          text: "近三日",
          range: latestType('threeDay')
        },
        {
          id: "latestWeek",
          text: "近一周",
          range: latestType('week')
        },
        {
          id: "latestMonth",
          text: "近一月",
          range: latestType('monthOne')
        },
        {
          id: "latestThreeMonth",
          text: "近三月",
          range: latestType('monthThree')
        },
      ],
      done: function (value, date, endDate) {
        setTimeout(function () {
          LatestAnnouncement.setAnnounceParam();
        }, 500);
      },
    });
    $(window).on("scroll", function () {
      //判断悬浮图标是否显示
      if (getScrollOffset().y > 300) {
        $(".sse_toTop").fadeIn();
      } else {
        $(".sse_toTop").fadeOut();
      }
    });
    //关键字输入框限制字符
    $(".js_keyWords .sse_input").attr("maxlength", "15");
    //mobile添加展开btn
    $(".search_inputCol").after(
      '<div class="leftShow">展开<span class="bi-chevron-double-down"></span></div>'
    );
    //替换市场类型输入框placeholder
    $(".js_typeList .sse_input").attr("placeholder", "类型编号/类型名称");
    //右侧悬浮按钮点击跳转至对应公告条数
    $(".sse_toTop").on("click", "li", function (e) {
      e.stopPropagation();
      var indexNum = $(this).index();
      if (indexNum == 0) {
        $("html,body").animate(
          {
            scrollTop: "0",
          },
          800
        );
      } else {
        var trHeight = $(".js_announceTable tbody tr")
          .eq((indexNum - 1) * 100)
          .offset().top;
        $("html,body").animate(
          {
            scrollTop: trHeight,
          },
          800
        );
      }
    });
    //市场类型赋值
    var selectHtm =
      '<option value="0">全部</option><option value="1">主板</option><option value="2">科创板</option>';
    //调用bootstrap-select
    bootstrapSelect({
      method: function () {
        $(".js_marketType .selectpicker")
          .html(selectHtm)
          .selectpicker("refresh")
          .selectpicker("render");
        //市场类型改变调用参数
        $(".js_marketType .selectpicker").on(
          "changed.bs.select",
          function (e, clickedIndex, isSelected, previousValue) {
            LatestAnnouncement.setAnnounceParam();
          }
        );
      },
    });

    //点击关键字搜索
    $(".search_btn").on("click", function (e) {
      e.stopPropagation();
      LatestAnnouncement.flag_param = true;
      LatestAnnouncement.setAnnounceParam();
    });

    //enter关键字
    $(".js_keyWords input").on(bind_name, function (e) {
      var keyCode = e.keyCode || e.which || e.charCode;
      if (keyCode == 13) {
        LatestAnnouncement.flag_param = true;
        LatestAnnouncement.setAnnounceParam();
      }
    });
    //证券代码拼接
    $(".js_code").append('<div class="errorMessage"></div>');
    //enter证券代码
    $(".js_code input").on(bind_name, function (e) {
      var keyCode = e.keyCode || e.which || e.charCode;
      if (keyCode == 13) {
        LatestAnnouncement.flag_param = true;
        LatestAnnouncement.setAnnounceParam();
      }
    });
    //公告类型选择
    $(".announceTypeList").on("click", ".big-type-title", function (e) {
      e.stopPropagation();
      LatestAnnouncement.flag_param = true;
      LatestAnnouncement.setAnnounceParam(1); //1代表点击之后，不符合条件不能设置选中
      var hasDel = false;
      if (LatestAnnouncement.toBoolean) {
        var hasActive = $(this).hasClass("big-active");
          if (hasActive) {
            if (
              $(this)
                .parents(".announceDiv")
                .find(".iconcirclecheckfull")
                .hasClass("isDel")
            ) {
              hasDel = true;
            }
            $(this)                                     
              .parents(".announceDiv")
              .find(".iconcirclecheckfull")
              .removeClass("iconcirclecheckfull")
              .addClass("iconcircle");
            $(this).removeClass("big-active");
            $(this).next().find("li").removeClass("big-active");
            if($(this).text() == '只看公告正文' || $(this).text() =='隻看公告正文'){
              LatestAnnouncement.hasDelMain = false;
            }
          } else {
            $(this)
              .parents(".announceDiv")
              .find(".iconcircle")
              .removeClass("iconcircle")
              .addClass("iconcirclecheckfull");
            $(this).addClass("big-active");
            $(this).next().find("li").addClass("big-active");
            if($(this).text() == '只看公告正文' || $(this).text() =='隻看公告正文'){
              LatestAnnouncement.hasDelMain = true;
            }
          }
          LatestAnnouncement.flag_param = true;
          LatestAnnouncement.addTypeStr(hasDel);
        }
    });
    //公告类型第二级类型
    $(".announceTypeList").eq(1).on("click", ".small-type-list li", function (e) {
      e.stopPropagation();
      LatestAnnouncement.flag_param = true;
      LatestAnnouncement.setAnnounceParam(1);
      if (LatestAnnouncement.toBoolean) {
        var hasActive = $(this).hasClass("big-active");
        if (hasActive) {
          $(this)
            .find(".iconcirclecheckfull")
            .removeClass("iconcirclecheckfull")
            .addClass("iconcircle");
          var firstTitle = $(this)
            .parents(".announceDiv")
            .find(".big-type-title");
          firstTitle.removeClass("big-active");
          firstTitle
            .find(".iconcirclecheckfull")
            .removeClass("iconcirclecheckfull")
            .addClass("iconcircle");
          $(this).removeClass("big-active");
        } else {
          $(this)
            .find(".iconcircle")
            .removeClass("iconcircle")
            .addClass("iconcirclecheckfull");
          var firstUl = $(this).parents(".small-type-list");
          if (
            firstUl.find("li").length ==
            firstUl.find(".iconcirclecheckfull").length
          ) {
            $(this)
              .parents(".announceDiv")
              .find(".big-type-title")
              .addClass("big-active");
            $(this)
              .parents(".announceDiv")
              .find(".big-type-title .iconfont")
              .addClass("iconcirclecheckfull")
              .removeClass("iconcircle");
          }
          $(this).addClass("big-active");
        }
        LatestAnnouncement.flag_param = true;
        LatestAnnouncement.addTypeStr();
      }
    });
    //左侧公告类型展开收起
    $(".announceShow").click(function (e) {
      e.stopPropagation();
      var has = $(".announceTypeList").eq(1).hasClass("hasShow");
      if (!has) {
        $(".announceTypeList").eq(1).addClass("hasShow");
        $(this).html(
          '收起全部<span class="bi-chevron-double-down type_closeUp"></span>'
        );
      } else {
        $(".announceTypeList").eq(1).removeClass("hasShow");
        $(this).html('展开全部<span class="bi-chevron-double-down"></span>');
      }
    });
    //左侧筛选条件手机端展开隐藏
    $(".sse_content").on("click", ".leftShow", function (e) {
      e.stopPropagation();
      var displayCss = $(".search_inputCol").css("display");
      if (displayCss == "block") {
        $(".search_inputCol").hide();
        $(this).html('展开<span class="bi-chevron-double-down"></span>');
      } else {
        $(".search_inputCol").show();
        $(this).html(
          '隐藏<span class="bi-chevron-double-down type_closeUp"></span>'
        );
      }
    });
    //按键keyup搜索公告类型
    $(".js_typeList input").on(bind_name, function () {
      var type_value = $(this).val(); //搜索词
      LatestAnnouncement.getAnnounceType(type_value);
    });

    /**输入框失去焦点搜索**/
    //关键字
    $(".js_keyWords input").on("blur", function () {
      LatestAnnouncement.setAnnounceParam();
    });
    //证券代码
    $(".js_code input")
      .on("blur", function () {
        $(".errorMessage").text("");
      })
      .on("blur", function () {
        setTimeout(function () {
          LatestAnnouncement.setAnnounceParam();
        }, 500);
      });
    /*输入框失去焦点搜索end*/

    //点击空白位置搜索
    $(document).on("click", function (e) {
      if (
        !$(".sse_searchInput").is(e.target) &&
        $(".sse_searchInput").has(e.target).length === 0 &&
        !$(".announceDiv").is(e.target) &&
        $(".announceDiv").has(e.target).length === 0 &&
        !$(".js_marketType").is(e.target) &&
        $(".js_marketType").has(e.target).length === 0 &&
        !$(".option_span em").is(e.target) &&
        $(".option_span em").has(e.target).length === 0 &&
        !$(".sse_toTop").is(e.target) &&
        $(".sse_toTop").has(e.target).length === 0 &&
        !$(".loading").is(e.target) &&
        $(".loading").has(e.target).length === 0 &&
        !$(".today_leftDate").is(e.target) &&
        $(".today_leftDate").has(e.target).length === 0
      ) {
        LatestAnnouncement.setAnnounceParam();
      }
    });
    //删除已筛选的条件
    $(".option_span").on("click", "i", function (e) {
      e.stopPropagation();
      var parentSpan = $(this).parent();
      //删除最后一个等同重置
      if ($(".option_span span").length == 1) {
        $(".select_reset").trigger("click");
        return;
      }
      //公告类型  多个根据name属性找到对应选项
      if (parentSpan.hasClass("filter-type")) {
        var nameOne = parentSpan.attr("name");
        if ($(".option_span span").length < 2) {
          $(".js_laydateSearch").text("");
          LatestAnnouncement.announceParam.START_DATE = "";
          LatestAnnouncement.announceParam.END_DATE = "";
        }
        $(this).parent().remove();
        // $(".announceTypeList").eq(0)
        //   .find("[name='" + nameOne + "']")
        //   .addClass("isDel")
        //   .click();
        $(".announceTypeList")
          .find("[name='" + nameOne + "']")
          .addClass("isDel")
          .click();
      } else {
        // 其他条件 单个
        if (parentSpan.hasClass("filter-market")) {
          $(".selectpicker").get(0).selectedIndex = 0; //select回到初始状态
          $(".selectpicker").selectpicker("refresh").selectpicker("render");
        } else if (parentSpan.hasClass("filter-title")) {
          $(".js_keyWords input").val("");
        } else if (parentSpan.hasClass("filter-code")) {
          $(".js_code input").val("");
          $(".js_laydateSearch").text("");
          LatestAnnouncement.announceParam.START_DATE = "";
          LatestAnnouncement.announceParam.END_DATE = "";
        }
        if ($(".option_span span").length < 2) {
          $(".js_laydateSearch").text("");
          LatestAnnouncement.announceParam.START_DATE = "";
          LatestAnnouncement.announceParam.END_DATE = "";
        }
        LatestAnnouncement.setAnnounceParam();
        $(this).parent().remove();
      }
    });
    //重置
    $(".select_reset").on("click", function (e) {
      e.stopPropagation();
      LatestAnnouncement.hasDelMain = false;
      //if ($(".option_span span").length > 0) {
      LatestAnnouncement.announceNumParam = {
        //公司，公告条数参数
        sqlId: "COMMON_PL_SSGSXX_ZXGG_NUM_L",
        START_DATE: "",
        END_DATE: "",
        SECURITY_CODE: "",
        TITLE: "",
        BULLETIN_TYPE: "",
        MAX_DATE: 1,
        type: "inParams",
      };
      //公告参数
      LatestAnnouncement.announceParam = {
        isPagination: true,
        "pageHelp.pageSize": 25,
        "pageHelp.cacheSize": 1,
        START_DATE: "",
        END_DATE: "",
        SECURITY_CODE: "",
        TITLE: "",
        BULLETIN_TYPE: "",
        stockType: "", // 1 =主板 ， 2=科创板，默认全部
      };
      //清空筛选条件--左侧输入框、类型清空
      $(".js_keyWords input").val("");
      $(".js_code input").val("");
      $(".errorMessage").text("");

      $(".selectpicker").get(0).selectedIndex = 0; //select回到初始状态
      $(".selectpicker").selectpicker("refresh").selectpicker("render");
      LatestAnnouncement.selectTypeNum = 0;

      $(".js_typeList input").val("");
      LatestAnnouncement.getAnnounceType("");
      $(".js_laydateSearch").text("");
      $(".iconcirclecheckfull")
        .removeClass("iconcirclecheckfull")
        .addClass("iconcircle");
      $(".big-active").removeClass("big-active");
      $(".see_noClick").removeClass("see_noClick");
      $(".option_span").html("");

      LatestAnnouncement.flag_param = false;

      if (clientWidth < 991) {
        $(".search_inputCol").hide();
        $(".leftShow").html('展开<span class="bi-chevron-double-down"></span>');
      }
      $(".js_laydateSpan").html(LatestAnnouncement.newDateTime);
      LatestAnnouncement.announceSortFile = "stock_bulletin_publish_order.json";
      LatestAnnouncement.announceCodeParam = {
        sortType: 1,
      };
      LatestAnnouncement.getCodeSort(); //获取静态公告
      LatestAnnouncement.getNumAnnounce(1); //获取公司、公告数量

      //}
      $(".announce_selectCon").removeClass("flex_wrap");
    });
    //点击获取证券排序的json数据
    $(".js_announceTable").on("click", ".js_code-th", function (e) {
      e.stopPropagation();
      if (LatestAnnouncement.announceCodeParam.sortType != 0) {
        LatestAnnouncement.announceCodeParam.sortNum = null;
        LatestAnnouncement.announceCodeParam.sortType = 0;
        LatestAnnouncement.announceSortFile = $(this).attr("name");
      }
      LatestAnnouncement.getCodeSort();
    });

    //点击发布时间排序获取json数据
    $(".js_announceTable").on("click", ".js_time-th", function (e) {
      e.stopPropagation();
      if (LatestAnnouncement.announceCodeParam.sortType == 0) {
        LatestAnnouncement.announceCodeParam.time = null;
        LatestAnnouncement.announceCodeParam.sortType = 1;
        LatestAnnouncement.announceSortFile = $(this).attr("name");
      }
      LatestAnnouncement.getCodeSort();
    });
  },
  //获取筛选条件
  setAnnounceParam: function (clickType) {
    /**获取参数值比较是否变化--flag_param 是判定参数*/
    LatestAnnouncement.toBoolean = true; //判定是否调用接口的参数

    //关键字
    var keyVal = $(".js_keyWords input").val();
    if (LatestAnnouncement.announceParam.TITLE != keyVal) {
      LatestAnnouncement.flag_param = true;
      LatestAnnouncement.announceParam.TITLE = keyVal;
    }
    //证券代码
    var codeVal = $(".js_code input").val();
    if (LatestAnnouncement.announceParam.SECURITY_CODE != codeVal) {
      LatestAnnouncement.flag_param = true;
      LatestAnnouncement.announceParam.SECURITY_CODE = codeVal;
    }
    //获取市场类型
    var selectType = $(".js_marketType .selectpicker").val();
    var selectVal = "";
    if (LatestAnnouncement.selectTypeNum != selectType) {
      LatestAnnouncement.flag_param = true;
      LatestAnnouncement.selectTypeNum = selectType;
    }
    if (selectType == 1) {
      selectVal = 1;
    } else if (selectType == 2) {
      selectVal = 2;
    } else {
      selectVal = "";
    }
    //如果与上一次取值不同则重新赋值
    if (LatestAnnouncement.announceParam.stockType != selectVal) {
      LatestAnnouncement.flag_param = true;
      LatestAnnouncement.announceParam.stockType = selectVal;
    }
    //日期范围
    var rangeTime = $(".js_laydateSearch").text();
    var times = rangeTime.split("-");
    var nowTime =
      LatestAnnouncement.announceParam.START_DATE &&
      LatestAnnouncement.announceParam.END_DATE
        ? LatestAnnouncement.announceParam.START_DATE.trim().replace(
            /-/g,
            "/"
          ) +
          " - " +
          LatestAnnouncement.announceParam.END_DATE.trim().replace(/-/g, "/")
        : "";
    if (nowTime.trim() != rangeTime.trim()) {
      LatestAnnouncement.flag_param = true;
      if (times.length > 1) {
        LatestAnnouncement.announceParam.START_DATE = times[0]
          .trim()
          .replace(/\//g, "-");
        LatestAnnouncement.announceParam.END_DATE = times[1]
          .trim()
          .replace(/\//g, "-");
      } else {
        LatestAnnouncement.announceParam.START_DATE = "";
        LatestAnnouncement.announceParam.END_DATE = "";
      }
    }
    /**获取参数值比较是否变化end*/
    if (LatestAnnouncement.flag_param) {
      LatestAnnouncement.flag_param = false;
      //证券代码存在，时间范围3年
      var isSixNum = new RegExp("^[0-9]{6}$");
      if (LatestAnnouncement.announceParam.SECURITY_CODE) {
        if (!isSixNum.test(LatestAnnouncement.announceParam.SECURITY_CODE)) {
          //验证证券代码
          $(".errorMessage").text("请输入正确的证券代码");
          LatestAnnouncement.toBoolean = false;
        } else {
          $(".errorMessage").text("");
          //时间为空取系统时间设置默认时间
          if (
            LatestAnnouncement.announceParam.START_DATE == "" &&
            LatestAnnouncement.announceParam.END_DATE == ""
          ) {
            LatestAnnouncement.announceParam.END_DATE =
              LatestAnnouncement.todayStr;
            LatestAnnouncement.announceParam.START_DATE = changeFormatDate(
              LatestAnnouncement.todayStr,
              0,
              0,
              -3
            ); //日期范围默认截止时间往前推3个月
          }
          //开始时间加3年与截止时间比较，小于0时间范围大于年，不合法
          var startYear = changeFormatDate(
            LatestAnnouncement.announceParam.START_DATE,
            0,
            0,
            3
          );
          if (
            new Date(startYear) -
              new Date(LatestAnnouncement.announceParam.END_DATE) <
            0
          ) {
            bootstrapModal({
              text: "查询只提供日期间隔不超过3年的公告",
            });
            LatestAnnouncement.toBoolean = false;
          }
        }
      } else {
        //时间为空取系统时间设置默认时间
        if (
          LatestAnnouncement.announceParam.START_DATE == "" &&
          LatestAnnouncement.announceParam.END_DATE == ""
        ) {
          LatestAnnouncement.announceParam.END_DATE =
            LatestAnnouncement.todayStr;
          LatestAnnouncement.announceParam.START_DATE = changeFormatDate(
            LatestAnnouncement.todayStr,
            0,
            -3,
            0
          ); //日期范围默认截止时间往前推3个月
        }
        //开始时间加3个月与截止时间比较，小于0时间范围大于3个月，不合法
        var startYear = changeFormatDate(
          LatestAnnouncement.announceParam.START_DATE,
          0,
          3,
          0
        );
        if (
          new Date(startYear) -
            new Date(LatestAnnouncement.announceParam.END_DATE) <
          0
        ) {
          bootstrapModal({
            text: "查询只提供日期间隔不超过3个月的公告",
          });
          LatestAnnouncement.toBoolean = false;
        }
      }
      var type01 =
        new Date(LatestAnnouncement.announceParam.START_DATE) -
        new Date("2015-05-01");
      var type02 =
        new Date(LatestAnnouncement.announceParam.START_DATE) -
        new Date("2019-07-01");
      if (selectType == 2) {
        if (type02 < 0) {
          $(".filter-type").remove();
          $(".iconcirclecheckfull")
            .removeClass("iconcirclecheckfull")
            .addClass("iconcircle");
          $(".big-active").removeClass("big-active");
          $(".announceTypeList").eq(1).addClass("see_noClick");
          LatestAnnouncement.announceParam.BULLETIN_TYPE = "";
        } else {
          $(".announceTypeList").eq(1).removeClass("see_noClick");
        }
      } else {
        if (type01 < 0) {
          $(".filter-type").remove();
          $(".iconcirclecheckfull")
            .removeClass("iconcirclecheckfull")
            .addClass("iconcircle");
          $(".big-active").removeClass("big-active");
          $(".announceTypeList").eq(1).addClass("see_noClick");
          LatestAnnouncement.announceParam.BULLETIN_TYPE = "";
        } else {
          $(".announceTypeList").eq(1).removeClass("see_noClick");
        }
      }
      if (LatestAnnouncement.toBoolean && clickType != 1) {
        LatestAnnouncement.getAllAnnounceList(1);
        //给获取公司、公告数的接口参数赋值
        LatestAnnouncement.announceNumParam.START_DATE =
          LatestAnnouncement.announceParam.START_DATE;
        LatestAnnouncement.announceNumParam.END_DATE =
          LatestAnnouncement.announceParam.END_DATE;
        LatestAnnouncement.announceNumParam.SECURITY_CODE =
          LatestAnnouncement.announceParam.SECURITY_CODE;
        LatestAnnouncement.announceNumParam.TITLE =
          LatestAnnouncement.announceParam.TITLE;
        LatestAnnouncement.announceNumParam.MAX_DATE = "";
        LatestAnnouncement.announceNumParam.BULLETIN_TYPE =
          LatestAnnouncement.announceParam.BULLETIN_TYPE;
        LatestAnnouncement.getNumAnnounce();
        //搜索内容添加cookie
        popularize.saveCpyIntoCookie(
          $("#inputCode").val().trim(),
          $("#inputCode"),
          1
        );
      }
      if (!LatestAnnouncement.toBoolean) {
        $(".js_laydateSearch").text(LatestAnnouncement.preTime);
        if (LatestAnnouncement.preTime != "") {
          var AllReplace = new RegExp("/", "g");
          LatestAnnouncement.announceParam.START_DATE =
            LatestAnnouncement.preTime.split(" - ")[0].replace(AllReplace, "-");
          LatestAnnouncement.announceParam.END_DATE = LatestAnnouncement.preTime
            .split(" - ")[1]
            .replace(AllReplace, "-");
        } else {
          LatestAnnouncement.announceParam.START_DATE = "";
          LatestAnnouncement.announceParam.END_DATE = "";
        }
      }
    }
  },
  /*重新渲染代码简称 */
  getGSJCS: function (callback) {
    //以代码为key简称为value 取出静态数据
    var wData = get_alldata();
    if (Object.keys(LatestAnnouncement.gsjcs).length == 0) {
      var gsjcss = {};
      for (var i in wData) {
        var obj = wData[i];
        gsjcss["s_" + obj.val] = obj.val2;
      }
      callback(gsjcss);
    } else {
      callback(LatestAnnouncement.gsjcs);
    }
  },
  //遍历tr，为简称赋值
  showGSJC: function () {
    LatestAnnouncement.getGSJCS(function (gs) {
      LatestAnnouncement.gsjcs = gs;
      $(".js_announceTable .table tr").each(function () {
        var _td = $(this).find("td");
        var td0 = _td.eq(0);
        var td1 = _td.eq(1);
        if (td1 && (td1.text() == "" || td1.text() == "-")) {
          //第一列代码为空时，存在主附件，简称与代码一致为空
          if(td0.text() && td0.text() != "" && td0.text() != '-'){
            var htmlStr = '<a target="_blank" href="/assortment/stock/list/info/company/index.shtml?COMPANY_CODE=' +
            td0.text() + '">' +
            (LatestAnnouncement.gsjcs["s_" + td0.text()] ? LatestAnnouncement.gsjcs["s_" + td0.text()] : "-") +
            "</a>";
            td1.html(htmlStr);
          } else {
            td1.text("");
          }
        }
      });
    });
  },
  /*重新渲染代码简称 end */
  //sortType : 1 是当前是时间排序  0当前是证券排序 ；sortNum、time 为null 是json文件数据的顺序，有值倒序
  getCodeSort: function () {
    var emptyTr = '<tr><td colspan="5">暂无数据</tr></tbody>';
    $.getJSON(
      LatestAnnouncement.announceFileUrl +
        LatestAnnouncement.announceSortFile +
        "?v=" +
        Math.random(),
      function (dataObj) {
        //获取公告默认结束时间
        if (dataObj && dataObj.publishData && dataObj.publishData.length > 0) {
          LatestAnnouncement.todayStr = dataObj.publishData[0].discloseDate
            ? dataObj.publishData[0].discloseDate.split(" ")[0]
            : get_systemDate_global();
        }
        //显示公告发布状态
        var publishStatus = dataObj.publishStatus;
        if (publishStatus != undefined) {
          $(".js_announceTable>img").remove();
          $(".js_announceTable").append(
            '<img alt="" src="/xhtml/images/zhushi' +
              (publishStatus == 1 ? "" : publishStatus || "") +
              '.gif">'
          );
        }
        if (dataObj && dataObj.publishData) {
          if (
            LatestAnnouncement.announceCodeParam.sortNum &&
            LatestAnnouncement.announceCodeParam.sortType == 0
          ) {
            LatestAnnouncement.announceCodeParam.sortNum = null;
          } else if (LatestAnnouncement.announceCodeParam.sortType == 0) {
            dataObj.publishData.reverse();
            LatestAnnouncement.announceCodeParam.sortNum = 1;
          } else if (
            LatestAnnouncement.announceCodeParam.time &&
            LatestAnnouncement.announceCodeParam.sortType == 1
          ) {
            dataObj.publishData.reverse();
            LatestAnnouncement.announceCodeParam.time = null;
          } else if (LatestAnnouncement.announceCodeParam.sortType == 1) {
            LatestAnnouncement.announceCodeParam.time = 1;
          }
          var announceHtml =
            "<thead>" +
            "<tr>" +
            '<th style="min-width: 80px;"  class="js_code-th text-nowrap" name="stock_bulletin_code_order.json">' +
            "证券代码" +
            '<span class="sort-span">' +
            '<em class="caret-em caret-em-down' +
            (!LatestAnnouncement.announceCodeParam.sortNum &&
            LatestAnnouncement.announceCodeParam.sortType == 0
              ? " caret-on"
              : "") +
            '"></em>' +
            '<em class="caret-em caret-em-up' +
            (LatestAnnouncement.announceCodeParam.sortNum &&
            LatestAnnouncement.announceCodeParam.sortType == 0
              ? " caret-on"
              : "") +
            '"></em>' +
            "</span>" +
            "</th>" +
            '<th class="text-nowrap">' +
            "证券简称" +
            "</th>" +
            "<th>公告标题</th>" +
            "<th></th>" +
            '<th class="js_time-th text-nowrap" name="stock_bulletin_publish_order.json">' +
            "公告时间" +
            '<span class="sort-span">' +
            '<em class="caret-em caret-em-down' +
            (!LatestAnnouncement.announceCodeParam.time &&
            LatestAnnouncement.announceCodeParam.sortType == 1
              ? " caret-on"
              : "") +
            '"></em><em class="caret-em caret-em-up' +
            (LatestAnnouncement.announceCodeParam.time &&
            LatestAnnouncement.announceCodeParam.sortType == 1
              ? " caret-on"
              : "") +
            '"></em>' +
            "</span>" +
            "</th>" +
            "</tr></thead><tbody>";
          $.each(dataObj.publishData, function (k, v) {
            announceHtml += "<tr>";
            announceHtml +=
              '<td class="text-nowrap"><a target="_blank" href="/assortment/stock/list/info/company/index.shtml?COMPANY_CODE=' +
              v.securityCode + '">'+
              (v.securityCode ? v.securityCode : "") +
              "</a></td>";
            announceHtml +=
              '<td class="text-nowrap"><a target="_blank" href="/assortment/stock/list/info/company/index.shtml?COMPANY_CODE=' +
              v.securityCode + '">' +
              (v.securityAbbr ? v.securityAbbr : "") +
              "</a></td>";
            announceHtml +=
              '<td><a class="table_titlewrap" href="' +
              staticBulletinUrl +
              (v.bulletinUrl ? v.bulletinUrl : "") +
              '" target="_blank"><span onclick="clickPdf($(this))">' +
              (v.isHolderDisclose == "1" ? "<em>股东自行披露</em>" : "") +
              (v.bulletinTitle ? v.bulletinTitle : "") +
              "</span></a></td>";
            announceHtml +=
              '<td class="text-center"><a class="iconfont iconxiazai" style="cursor: pointer;color: #bc0007 !important" href="' +
              (v.bulletinUrl ? v.bulletinUrl : "") +
              '" title="点击下载公告文件" download="'+(v.securityCode ? v.securityCode + '_' : "") + (v.discloseDate ? v.discloseDate.substring(0,10).replace(/-/g, '') + '_' : "") + (v.bulletinTitle ? v.bulletinTitle + obtainFileType(v.bulletinUrl) : "文件"+ obtainFileType(v.bulletinUrl))+'"></a></td>'; //下载
            announceHtml +=
              '<td class="text-nowrap">' +
              (v.discloseDate ? v.discloseDate : "") +
              "</td>";
            announceHtml += "</tr>";
          });
          if (dataObj.publishData.length == 0) {
            announceHtml += emptyTr;
            //数据为0隐藏右侧浮动
            $(".sse_toTop ul").hide();
          } else {
            //显示右侧浮动 100、200、300
            $(".sse_toTop ul").show();
            var liNum = parseInt(dataObj.publishData.length / 100) + 1;
            var oneLi = '<li><span class="bi-chevron-bar-up"></span></li>';
            for (var i = 0; i < liNum; i++) {
              oneLi += "<li><a>" + (i == 0 ? 1 : i * 100) + "</a></li>";
            }
            $(".sse_toTop ul").html(oneLi);
          }
        } else {
          var announceHtml =
            '<thead><tr><th style="min-width: 80px;"  class="js_code-th text-nowrap" name="stock_bulletin_code_order.json">证券代码<span class="sort-span"><em class="caret-em caret-em-down"></em><em class="caret-em caret-em-up></em></span></th><th class="text-nowrap">证券简称</th><th>公告标题</th><th>公告分类</th><th class="js_time-th text-nowrap" name="stock_bulletin_publish_order.json">公告时间<span class="sort-span"><em class="caret-em caret-em-down></em><em class="caret-em caret-em-up caret-on"></em></span></th></tr></thead><tbody>';
          announceHtml += emptyTr;
        }
        announceHtml += "</tbody>";
        $(".js_announceTable .table").html(announceHtml);
      }
    );
    $(".js_announceTable .pagination-box").html("");
  },
  //公告类型静态展示
  getTypeList: function () {
    $.getJSON(
      "/xhtml/disclosure/listedinfo/announcement/json/" +
      LatestAnnouncement.announceTypeUrl +
      "?v=" +
      Math.random(),
      function (data) {
        if (data && data.publishData) {
          var type_div = "";
          for (var i = 0; i < data.publishData.length; i++) {
            type_div +=
              '<div class="announceDiv ' +
              (i == 0 ? "announce-child" : "") +
              '">';
            type_div +=
              '<div class="big-type-title"><span class="iconfont iconcircle" name="' +
              data.publishData[i].announceTypeCode +
              '"></span><b class="btype-id">' +
              data.publishData[i].announceTypeId +
              '</b>.<b class="btype-name">' +
              data.publishData[i].announceTypeName +
              "</b></div>";
            if (data.publishData[i].childData) {
              type_div += '<ul class="small-type-list">';
              for (var j = 0; j < data.publishData[i].childData.length; j++) {
                type_div +=
                  '<li><span class="iconfont iconcircle" name="' +
                  data.publishData[i].childData[j].announceTypeCode +
                  '"></span>' +
                  data.publishData[i].childData[j].announceTypeName +
                  "</li>";
              }
              type_div += "</ul>";
            }
            type_div += "</div>";
          }
          $(".announceTypeList").eq(1).html(type_div);
        }
      }
    );
  },
  //获取公司家数，公告条数
  getNumAnnounce: function (initNum) {
    var company = 0; //公司数据量
    var bulletin = 0; //公告数量
    LatestAnnouncement.newDateTime = ""; //页面日期
    if(isNull(LatestAnnouncement.announceNumParam.BULLETIN_TYPE)){
      LatestAnnouncement.announceNumParam.BULLETIN_TYPE = LatestAnnouncement.announceNumParam.BULLETIN_TYPE.replace('hasDelMain','');
      if(LatestAnnouncement.announceNumParam.BULLETIN_TYPE.substring(0,1) == ','){
        LatestAnnouncement.announceNumParam.BULLETIN_TYPE = LatestAnnouncement.announceNumParam.BULLETIN_TYPE.slice(1);
      }
    }
    getJSON(
      LatestAnnouncement.announceNumUrl,
      LatestAnnouncement.announceNumParam,
      function (data) {
        if (data && data.result && data.result.length > 0) {
          if (LatestAnnouncement.selectTypeNum == 1) {
            //主板取第一条
            company =
              data.result[0].BULLETIN_DATE &&
              data.result[0].BULLETIN_DATE != "-"
                ? data.result[0].COMPANY_NUM
                : 0;
            bulletin =
              data.result[0].BULLETIN_DATE &&
              data.result[0].BULLETIN_DATE != "-"
                ? data.result[0].BULLETIN_NUM
                : 0;
            LatestAnnouncement.newDateTime =
              data.result[0].BULLETIN_DATE &&
              data.result[0].BULLETIN_DATE != "-"
                ? data.result[0].BULLETIN_DATE
                : LatestAnnouncement.todayStr;
          } else if (LatestAnnouncement.selectTypeNum == 2) {
            //科创板取第二条
            company =
              data.result[1].BULLETIN_DATE &&
              data.result[1].BULLETIN_DATE != "-"
                ? data.result[1].COMPANY_NUM
                : 0;
            bulletin =
              data.result[1].BULLETIN_DATE &&
              data.result[1].BULLETIN_DATE != "-"
                ? data.result[1].BULLETIN_NUM
                : 0;
            LatestAnnouncement.newDateTime =
              data.result[1].BULLETIN_DATE &&
              data.result[1].BULLETIN_DATE != "-"
                ? data.result[1].BULLETIN_DATE
                : LatestAnnouncement.todayStr;
          } else {
            //全部
            //返回的2条数据，如果都存在，两个日期相等，公司、公告数量取和，日期不相等取最新的数据
            if (
              data.result[0].BULLETIN_DATE != "-" &&
              data.result[0].BULLETIN_DATE != "" &&
              data.result[1].BULLETIN_DATE != "-" &&
              data.result[1].BULLETIN_DATE != ""
            ) {
              if (
                data.result[0].BULLETIN_DATE == data.result[1].BULLETIN_DATE ||
                LatestAnnouncement.announceNumParam.MAX_DATE != "1"
              ) {
                company =
                  parseInt(data.result[0].COMPANY_NUM) +
                  parseInt(data.result[1].COMPANY_NUM);
                bulletin =
                  parseInt(data.result[0].BULLETIN_NUM) +
                  parseInt(data.result[1].BULLETIN_NUM);
                LatestAnnouncement.newDateTime = data.result[0].BULLETIN_DATE;
                //判断时间大小，取最大值
              } else if (
                new Date(data.result[0].BULLETIN_DATE) >
                new Date(data.result[1].BULLETIN_DATE)
              ) {
                company = data.result[0].COMPANY_NUM;
                bulletin = data.result[0].BULLETIN_NUM;
                LatestAnnouncement.newDateTime = data.result[0].BULLETIN_DATE;
              } else {
                company = data.result[1].COMPANY_NUM;
                bulletin = data.result[1].BULLETIN_NUM;
                LatestAnnouncement.newDateTime = data.result[1].BULLETIN_DATE;
              }
            } else if (
              data.result[0].BULLETIN_DATE == "-" &&
              data.result[1].BULLETIN_DATE == "-"
            ) {
              //如果初始化返回数据是无效的，日期取当前日期，公司、公告数量默认0
              LatestAnnouncement.newDateTime = LatestAnnouncement.todayStr;
            } else {
              //如果其中一个数据存在，日期、公司公告数量取自那条数据
              company =
                data.result[0].BULLETIN_DATE &&
                data.result[0].BULLETIN_DATE != "-"
                  ? data.result[0].COMPANY_NUM
                  : data.result[1].COMPANY_NUM;
              bulletin =
                data.result[0].BULLETIN_DATE &&
                data.result[0].BULLETIN_DATE != "-"
                  ? data.result[0].BULLETIN_NUM
                  : data.result[1].BULLETIN_NUM;
              LatestAnnouncement.newDateTime =
                data.result[0].BULLETIN_DATE &&
                data.result[0].BULLETIN_DATE != "-"
                  ? data.result[0].BULLETIN_DATE
                  : data.result[1].BULLETIN_DATE;
            }
          }
        }
        //initNum 为1 是公告为静态数据时，页面时间显示接口的单个日期，不为1时 -- 页面时间显示公告查询的时间范围
        if (initNum == 1) {
          var defaultDate = LatestAnnouncement.newDateTime.replace(/\-/g, "/");
          $(".js_laydateSearch").attr(
            "lay-date",
            defaultDate + " - " + defaultDate
          );
          LatestAnnouncement.newDateTime = LatestAnnouncement.newDateTime
            ? LatestAnnouncement.newDateTime
                .replace("-", "年")
                .replace("-", "月") + "日"
            : LatestAnnouncement.todayStr;
          $(".js_laydateSpan").html(LatestAnnouncement.newDateTime);
        }
        $(".companyNum").text((company || company == 0 ? company : "") + "家");
        $(".bulletinNum").text(
          (bulletin || bulletin == 0 ? bulletin : "") + "条"
        );
      },
      function () {
        if (initNum == 1) {
          LatestAnnouncement.newDateTime = LatestAnnouncement.newDateTime
            ? LatestAnnouncement.newDateTime
                .replace("-", "年")
                .replace("-", "月") + "日"
            : LatestAnnouncement.todayStr;
          $(".js_laydateSpan").html(LatestAnnouncement.newDateTime);
        }
        $(".companyNum").text("0家");
        $(".bulletinNum").text("0条");
      }
    );
  },
  //搜索公告类型--不在搜索范围的 + hideDiv 隐藏
  getAnnounceType: function (typeVal) {
    $(".hideDiv").removeClass("hideDiv");
    var reg = /^[0-9]*$/;
    $(".js_typeListUl .announceDiv").each(function (index) {
      var oneId = $(this).find(".btype-id").text();
      var oneName = $(this).find(".btype-name").text();
      var liList = $(this).find("li");
      //如果输入的是数字 匹配id
      if (reg.test(typeVal)) {
        if (oneId.indexOf(typeVal) == -1) {
          $(this).addClass("hideDiv");
        }
      } else {
        //匹配name
        var childHas = false;
        if (oneName.indexOf(typeVal) != -1) {
          childHas = true;
        } else {
          for (var i = 0; i < liList.length - 1; i++) {
            var twoName = liList.eq(i).text();
            if (twoName.indexOf(typeVal) != -1) {
              childHas = true;
            }
          }
        }
        if (!childHas) {
          $(this).addClass("hideDiv");
        }
      }
    });

    if ($(".announceDiv:hidden").length < 30) {
      $(".announceShow").show();
      $(".announceTypeList").eq(1).removeClass("hasShow");
      $(".announceShow").html(
        '展开全部<span class="bi-chevron-double-down"></span>'
      );
    } else {
      $(".announceShow").hide();
      $(".announceTypeList").eq(1).addClass("hasShow");
    }
  },
  //公告类型的参数拼接
  addTypeStr: function (del) {
    var announceTypeCode = ""; //拼接code
    $(".iconcirclecheckfull").each(function (index) {
      var parentsHide = $(this).parents(".announceDiv");
      var typeName = $(this).attr("name");
      announceTypeCode += typeName + ",";
    });
    LatestAnnouncement.announceParam.BULLETIN_TYPE = announceTypeCode.substring(
      0,
      announceTypeCode.length - 1
    );
    if (
      del &&
      LatestAnnouncement.announceParam.BULLETIN_TYPE == "" &&
      $(".filter-code").length == 0 &&
      $(".filter-market").length == 0 &&
      $(".filter-title").length == 0
    ) {
      $(".select_reset").trigger("click");
    } else {
      LatestAnnouncement.setAnnounceParam();
    }
    $(".isDel").removeClass("isDel");
  },
  //调用公告接口
  getAllAnnounceList: function (pageIndex) {
    if(isNull(LatestAnnouncement.announceParam.BULLETIN_TYPE)){
      LatestAnnouncement.announceParam.BULLETIN_TYPE = LatestAnnouncement.announceParam.BULLETIN_TYPE.replace('hasDelMain','');
      if(LatestAnnouncement.announceParam.BULLETIN_TYPE.substring(0,1) == ','){
        LatestAnnouncement.announceParam.BULLETIN_TYPE = LatestAnnouncement.announceParam.BULLETIN_TYPE.slice(1);
      }
    }
    if (!paginationChange(LatestAnnouncement.announceParam, pageIndex)) {
      //触发分页改变分页参数
      return;
    }
    //gio最新公告筛选埋点
    var _sseMarketType_var = "";
    if (LatestAnnouncement.announceParam.stockType == "") {
      _sseMarketType_var = "全部";
    } else if (LatestAnnouncement.announceParam.stockType == "1") {
      _sseMarketType_var = "主板";
    } else if (LatestAnnouncement.announceParam.stockType == "2") {
      _sseMarketType_var = "科创板";
    }
    gdp("track", "sseStockAnnouncementClick", {
      sseSecurityCode_var: LatestAnnouncement.announceParam.SECURITY_CODE,
      sseMarketType_var: _sseMarketType_var,
      sseKey_var: LatestAnnouncement.announceParam.TITLE,
      sseOnlyMainBody_var: LatestAnnouncement.hasDelMain == true ? "是" : "否",
      sseAnnouncementType_var: LatestAnnouncement.announceParam.BULLETIN_TYPE,
      sseStartDate_var: LatestAnnouncement.announceParam.START_DATE,
      sseEndDate_var: LatestAnnouncement.announceParam.END_DATE,
    });

    var announceHtml =
      '<thead><tr><th class="text-nowrap">证券代码</th><th class="text-nowrap">证券简称</th><th>公告标题</th><th></th><th>公告分类</th><th class="text-nowrap">公告时间</th></tr></thead><tbody>';
    var emptyTr = '<tr><td colspan="5">暂无数据</tr>';
    getJSON(
      LatestAnnouncement.announceUrl,
      LatestAnnouncement.announceParam,
      function (data) {
        if (data && data.result && data.result.length > 0) {
          for (var i = 0; i < data.result.length; i++) {
            var j = data.result[i].length; // 本条数量
            $.each(data.result[i], function (k, v) {
              if (v.TITLE) {
                if(LatestAnnouncement.hasDelMain){
                  if(k == 0){
                    announceHtml +=
                    '<tr>';
                    if(v.SECURITY_CODE && v.SECURITY_CODE != '' && v.SECURITY_CODE != '-'){
                      announceHtml +=
                        '<td class="text-nowrap"><a target="_blank" href="/assortment/stock/list/info/company/index.shtml?COMPANY_CODE=' +
                        v.SECURITY_CODE + '">'+
                        (v.SECURITY_CODE ? v.SECURITY_CODE : "")+
                        "</a></td>";
                      announceHtml +=
                        '<td class="text-nowrap"><a target="_blank" href="/assortment/stock/list/info/company/index.shtml?COMPANY_CODE=' +
                        v.SECURITY_CODE + '">'+
                        (v.SECURITY_NAME ? v.SECURITY_NAME : "-") +
                        "</a></td>";
                    } else {
                      announceHtml +=
                        '<td class="text-nowrap">'+
                        (v.SECURITY_CODE ? v.SECURITY_CODE : "") +
                        "</td>";
                      announceHtml +=
                        '<td class="text-nowrap">'+
                        (v.SECURITY_NAME ? v.SECURITY_NAME : "-") +
                        "</td>";
                    }
                    announceHtml +=
                      '<td><a class="table_titlewrap" href="' +
                      staticBulletinUrl +
                      (v.URL ? v.URL : "") +
                      '" target="_blank"><span onclick="clickPdf($(this))">' +
                      (v.IS_HOLDER_DISCLOSE == 1 ? "<em>股东自行披露</em>" : "") +
                      (v.TITLE ? v.TITLE : "") +
                      "</span></a></td>";
                    announceHtml +=
                      '<td class="text-center"><a class="iconfont iconxiazai" style="cursor: pointer;color: #bc0007 !important" href="' +
                      (v.URL ? v.URL : "") +
                      '" title="点击下载公告文件" download="'+(v.SECURITY_CODE ? v.SECURITY_CODE + '_' : "") + (v.SSEDATE ? v.SSEDATE.substring(0,10).replace(/-/g, '') + '_' : "") + (v.TITLE ? v.TITLE + obtainFileType(v.URL) : "文件"+ obtainFileType(v.URL))+'"></a></td>'; //下载  
                    announceHtml +=
                      '<td><span class="table_typewrap">' +
                      (v.BULLETIN_TYPE_DESC ? v.BULLETIN_TYPE_DESC : "") +
                      "</span></td>";
                    announceHtml +=
                      '<td class="text-nowrap">' +
                      (v.SSEDATE ? v.SSEDATE : "") +
                      "</td>";
                  }
                } else {
                  announceHtml +=
                  '<tr class="' +
                  (j > 1 ? "multiple_bag" : "") +
                  (j > 1 && k == 0 ? " first_multiple" : "") +
                  (j > 1 && k == j - 1 ? " last_multiple" : "") +
                  '" '+'>';
                  if(v.SECURITY_CODE && v.SECURITY_CODE != '' && v.SECURITY_CODE != '-'){
                    announceHtml +=
                      '<td class="text-nowrap"><a target="_blank" href="/assortment/stock/list/info/company/index.shtml?COMPANY_CODE=' +
                      v.SECURITY_CODE + '">'+
                      (k == 0 ? (v.SECURITY_CODE ? v.SECURITY_CODE : "") : "") +
                      "</a></td>";
                    announceHtml +=
                      '<td class="text-nowrap"><a target="_blank" href="/assortment/stock/list/info/company/index.shtml?COMPANY_CODE=' +
                      v.SECURITY_CODE + '">'+
                      (k == 0 ? (v.SECURITY_NAME ? v.SECURITY_NAME : "-") : "") +
                      "</a></td>";
                  } else {
                    announceHtml +=
                      '<td class="text-nowrap">'+
                      (k == 0 ? (v.SECURITY_CODE ? v.SECURITY_CODE : "") : "") +
                      "</td>";
                    announceHtml +=
                      '<td class="text-nowrap">'+
                      (k == 0 ? (v.SECURITY_NAME ? v.SECURITY_NAME : "-") : "") +
                      "</td>";
                  }
                  announceHtml +=
                    '<td><a class="table_titlewrap" href="' +
                    staticBulletinUrl +
                    (v.URL ? v.URL : "") +
                    '" target="_blank"><span onclick="clickPdf($(this))">' +
                    (v.IS_HOLDER_DISCLOSE == 1 ? "<em>股东自行披露</em>" : "") +
                    (v.TITLE ? v.TITLE : "") +
                    "</span></a></td>";
                  announceHtml +=
                    '<td class="text-center"><a class="iconfont iconxiazai" style="cursor: pointer;color: #bc0007 !important" href="' +
                    (v.URL ? v.URL : "") +
                    '" title="点击下载公告文件" download="'+(v.SECURITY_CODE ? v.SECURITY_CODE + '_' : "") + (v.SSEDATE ? v.SSEDATE.substring(0,10).replace(/-/g, '') + '_' : "") + (v.TITLE ? v.TITLE + obtainFileType(v.URL) : "文件"+ obtainFileType(v.URL))+'"></a></td>'; //下载  
                  announceHtml +=
                    '<td><span class="table_typewrap">' +
                    (v.BULLETIN_TYPE_DESC ? v.BULLETIN_TYPE_DESC : "") +
                    "</span></td>";
                  announceHtml +=
                    '<td class="text-nowrap">' +
                    (v.SSEDATE ? v.SSEDATE : "") +
                    "</td>";
                }
              }
            });
            announceHtml += "</tr>";
          }
          if (data.result.length == 0) {
            announceHtml += emptyTr;
          }
          announceHtml += "</tbody>";
          $(".js_announceTable .table").html(announceHtml);
          Page.navigation(
            ".js_announceTable .pagination-box",
            data.pageHelp.pageCount,
            data.pageHelp.total,
            data.pageHelp.pageNo,
            data.pageHelp.pageSize,
            "LatestAnnouncement.getAllAnnounceList"
          );
        } else {
          announceHtml += emptyTr;
          announceHtml += "</tbody>";
          $(".js_announceTable .table").html(announceHtml);
          $(".js_announceTable .pagination-box").html("");
        }
        LatestAnnouncement.showGSJC();
        //跳回第一条
        //var trHeight = $(".js_announceTable tr").eq(0).offset().top;
        //Page.setTops(trHeight);
        $(".sse_toTop ul").hide();
        //当前时间输入框赋值
        $(".js_laydateSearch").text(
          LatestAnnouncement.announceParam.START_DATE.replace(/-/g, "/") +
            " - " +
            LatestAnnouncement.announceParam.END_DATE.replace(/-/g, "/")
        );
        $(".js_laydateSearch").attr(
          "lay-date",
          LatestAnnouncement.announceParam.START_DATE.replace(/-/g, "/") +
            " - " +
            LatestAnnouncement.announceParam.END_DATE.replace(/-/g, "/")
        );
        /** 筛选条件赋值 */
        //市场类型
        var selectArr = ["全部", "主板", "科创板"];
        var selectValue = $(".js_marketType .selectpicker").val();
        var searchHtm =
          selectValue != "" && selectValue != "0"
            ? '<span class="filter-market">' +
              selectArr[selectValue] +
              '<i class="bi-x-circle-fill"></i></span>'
            : "";
        //关键字
        searchHtm +=
          LatestAnnouncement.announceParam.TITLE != ""
            ? '<span class="filter-title">' +
              LatestAnnouncement.announceParam.TITLE +
              '<i class="bi-x-circle-fill"></i></span>'
            : "";
        //证券代码
        searchHtm +=
          LatestAnnouncement.announceParam.SECURITY_CODE != ""
            ? '<span class="filter-code">' +
              LatestAnnouncement.announceParam.SECURITY_CODE +
              '<i class="bi-x-circle-fill"></i></span>'
            : "";
        //日期范围
        var rangeDate =
          LatestAnnouncement.announceParam.START_DATE.replace(
            "-",
            "年"
          ).replace("-", "月") +
          "日 - " +
          LatestAnnouncement.announceParam.END_DATE.replace("-", "年").replace(
            "-",
            "月"
          ) +
          "日";
        $(".js_laydateSpan").html(
          rangeDate != "" ? rangeDate : LatestAnnouncement.newDateTime
        );
        var AllReplace = new RegExp("-", "g");
        LatestAnnouncement.preTime =
          LatestAnnouncement.announceParam.START_DATE.replace(AllReplace, "/") +
          " - " +
          LatestAnnouncement.announceParam.END_DATE.replace(AllReplace, "/");

        //公告类型
        $(".iconcirclecheckfull").each(function (index) {
          var typeTxt = $(this).parent().text();
          searchHtm +=
            typeTxt != ""
              ? '<span class="filter-type" name="' +
                $(this).attr("name") +
                '">' +
                typeTxt +
                '<i class="bi-x-circle-fill"></i></span>'
              : "";
        });
        $(".option_span").html(searchHtm);
        //筛选条件换行添加class
        if ($(".option_span").children()) {
          $(".announce_selectCon").addClass("flex_wrap");
        }
      },
      function () {
        announceHtml += emptyTr;
        announceHtml += "</tbody>";
        $(".js_announceTable .table").html(announceHtml);
        //隐藏右侧浮动 100、200、300
      }
    );
    //隐藏右侧浮动 100、200、300
    $(".sse_toTop ul").hide();
    $(".js_announceTable>img").remove();
  },
};
if ($(".js_announceTable").length > 0) {
  LatestAnnouncement.init();
}

//gio最新公告pdf点击事件埋点
function clickPdf (t) {
  gdp("track", "sseStockAnnouncementClick", {
    sseCheckPdf_var: t.text(),
  });
}
/***	最新公告end */

/**
 * 发行上市公告
 */
var listing = {
  listingUrl: sseQueryURL + "security/stock/queryCompanyBulletin.do",
  listingParams: {
    isPagination: true,
    "pageHelp.pageSize": 25,
    "pageHelp.pageNo": 1,
    "pageHelp.beginPage": 1,
    "pageHelp.cacheSize": 1,
    "pageHelp.endPage": 1,
    productId: "", //证券代码
    securityType: "0101,120100,020100,020200,120200",
    reportType2: "LSGG",
    reportType: "FXSSGG",
    beginDate: "",
    endDate: "",
  },
  init: function () {
    var _this = this;
    $.getScript(
      "/js/common/companyissuebulletinInformation/companyissuebulletin_new.js",
      function () {
        _this.staticListingList();
      }
    );
    triggerSearch(_this.setListingParams); //点击搜索、回车触发查询
  },
  staticListingList: function () {
    var _this = this;
    laydate({
      elem: ".js_dateRange input",
      theme: "#b50005",
      format: "yyyy-MM-dd",
      range: true,
      min: "1990-12-19",
      trigger: "click",
      btns: ["confirm"],
      done: function (value, date, endDate) {
        //选择时间触发查询
        setTimeout(function () {
          _this.setListingParams();
        }, 500);
      },
    });
    //获取发行上市公告静态数据
    var staticData = get_issureBulletin();
    var emptyTr = '<tr><td colspan="4">暂无数据</td></tr>';
    var listingHtml = "<thead><tr>";
    listingHtml += "<th>证券代码</th>";
    listingHtml += "<th>证券简称</th>";
    listingHtml += "<th>公告标题</th>";
    listingHtml += "<th>公告时间</th>";
    listingHtml += "</tr></thead><tbody>";
    //如果静态数据为空
    if (isBlankOrNull(staticData)) {
      $(".js_listing .table").html(listingHtml + emptyTr);
    } else {
      //日期赋值
      $(".js_dateRange input").val(
        staticData[staticData.length - 1].SSEDATE +
          " - " +
          staticData[0].SSEDATE
      );
      $.each(staticData, function (k, v) {
        listingHtml += "<tr>";
        listingHtml +=
          '<td class="codeNameWidth"><span>' + v.SECURITY_CODE + "</span></td>";
        listingHtml +=
          '<td class="codeNameWidth"><span>' +
          (v.SECURITY_NAME && v.SECURITY_NAME.toLowerCase() != "null"
            ? v.SECURITY_NAME
            : "-") +
          "</span></td>";
        listingHtml +=
          '<td><a class="table_titlewrap" target="_blank" href="' +
          staticBulletinUrl +
          v.URL +
          '"><span onclick="clickIPOPdf($(this))">' +
          v.TITLE +
          "</span></a></td>";
        listingHtml += '<td class="text-nowrap">' + v.SSEDATE + "</td>";
        listingHtml += "</tr>";
      });
      listingHtml += "</tbody>";
      $(".js_listing .table").html(listingHtml);
    }
  },
  setListingParams: function () {
    var _this = listing;
    _this.listingParams.productId = $("#inputCode").val();
    _this.listingParams.beginDate = $(".js_dateRange input")
      .val()
      .substr(0, 10);
    _this.listingParams.endDate = $(".js_dateRange input").val().substr(-10);
    //代码时间都为空
    if (
      _this.listingParams.productId == "" &&
      _this.listingParams.beginDate == ""
    ) {
      bootstrapModal({
        text: "请您指定证券代码或日期后再进行查询",
      });
      //证券代码为空，时间不为空
    } else if (
      _this.listingParams.productId == "" &&
      _this.listingParams.beginDate != ""
    ) {
      if (
        !IsDayLimit(
          _this.listingParams.beginDate,
          _this.listingParams.endDate,
          30,
          0,
          0
        )
      ) {
        bootstrapModal({
          text: "您未指定证券代码，查询将只提供日期间隔不超过30天的公告",
        });
      } else if (_this.listingParams.beginDate > _this.listingParams.endDate) {
        bootstrapModal({
          text: "开始日期不能大于结束日期",
        });
        return;
      } else {
        //调用接口
        _this.getListingList(1);
      }
      //代码时间都不为空
    } else if (
      _this.listingParams.productId != "" &&
      _this.listingParams.beginDate != ""
    ) {
      if (_this.listingParams.beginDate > _this.listingParams.endDate) {
        bootstrapModal({
          text: "开始日期不能大于结束日期",
        });
        return;
      }
      if (
        !IsDayLimit(
          _this.listingParams.beginDate,
          _this.listingParams.endDate,
          0,
          0,
          3
        )
      ) {
        bootstrapModal({
          text: "查询只提供日期间隔不超过3年的公告。",
        });
      } else if (isNaN(_this.listingParams.productId)) {
        bootstrapModal({
          text: "证券代码必须为6位数字，请根据智能提示选择证券代码后查询",
        });
      } else if (_this.listingParams.productId.length != 6) {
        bootstrapModal({
          text: "证券代码必须为6位数字",
        });
      } else {
        //调用接口
        _this.getListingList(1);
      }
    } else {
      bootstrapModal({
        text: "请您指定证券代码或日期后再进行查询",
      });
    }
  },
  getListingList: function (pageIndex) {
    var _this = this;
    if (!paginationChange(_this.listingParams, pageIndex)) {
      //修改分页参数
      return;
    }

    //gio发行上市公告筛选埋点
    gdp("track", "sseIPOAnnouncementClick", {
      sseSecurityCode_var: _this.listingParams.productId,
      sseStartDate_var: _this.listingParams.beginDate,
      sseEndDate_var: _this.listingParams.endDate,
    });

    var emptyTr = '<tr><td colspan="4">暂无数据</td></tr>';
    var listingHtml = "<thead><tr>";
    listingHtml += "<th>证券代码</th>";
    listingHtml += "<th>证券简称</th>";
    listingHtml += "<th>公告标题</th>";
    listingHtml += "<th>公告时间</th>";
    listingHtml += "</tr></thead><tbody>";
    getJSONP({
      type: "post",
      url: _this.listingUrl,
      data: _this.listingParams,
      dataType: "jsonp",
      successCallback: function (data) {
        if (data && data.result && data.result.length > 0) {
          $.each(data.result, function (k, v) {
            listingHtml += "<tr>";
            listingHtml +=
              '<td class="codeNameWidth"><span>' +
              v.SECURITY_CODE +
              "</span></td>";
            listingHtml +=
              '<td class="codeNameWidth"><span>' +
              (v.SECURITY_NAME && v.SECURITY_NAME.toLowerCase() != "null"
                ? v.SECURITY_NAME
                : "-") +
              "</span></td>";
            listingHtml +=
              '<td><a class="table_titlewrap" target="_blank" href="' +
              staticBulletinUrl +
              v.URL +
              '"><span onclick="clickIPOPdf($(this))">' +
              v.TITLE +
              "</span></a></td>";
            listingHtml += '<td class="text-nowrap">' + v.SSEDATE + "</td>";
            listingHtml += "</tr>";
          });
          listingHtml += "</tbody>";
          $(".js_listing .table").html(listingHtml);
          //调用分页
          Page.navigation(
            ".js_listing .pagination-box",
            data.pageHelp.pageCount,
            data.pageHelp.total,
            data.pageHelp.pageNo,
            data.pageHelp.pageSize,
            "listing.getListingList"
          );
        } else {
          listingHtml += emptyTr;
          listingHtml += "</tbody>";
          $(".js_listing .table").html(listingHtml);
          $(".js_listing .pagination-box").html("");
        }
        //搜索代码添加cookie
        popularize.saveCpyIntoCookie(
          $("#inputCode").val().trim(),
          $("#inputCode"),
          1
        );
      },
      errCallback: function () {
        listingHtml += emptyTr;
        listingHtml += "</tbody>";
        $(".js_listing .table").html(listingHtml);
        $(".js_listing .pagination-box").html("");
      },
    });
  },
};
if ($(".js_listing").length > 0) {
  listing.init();
}

//gio发行上市公告pdf点击事件埋点
function clickIPOPdf (t) {
  gdp("track", "sseIPOAnnouncementClick", {
    sseCheckPdf_var: t.text(),
  });
}
//发行上市公告end

/**
 * 定期报告预约情况
 */
var periodic = {
  periodicUrl: sseQueryURL + "commonSoaQuery.do",
  periodicParams: {
    sqlId: "SSE_SZSGG_DQBGYYQK_CAST_NEW",
    isPagination: true,
    "pageHelp.pageSize": 25,
    "pageHelp.pageNo": 1,
    "pageHelp.beginPage": 1,
    "pageHelp.cacheSize": 1,
    "pageHelp.endPage": 1,
    bulletintype: "",
    publishYear: "",
    companyCode: "",
    startTime: "",
    order: "companyCode|asc",
  },
  //排序字段
  companyOrder: "companyCode,desc",
  actualDateOrder: "actualDate,desc",
  publishOrder0: "publishDate0,desc",
  publishOrder1: "publishDate1,desc",
  publishOrder2: "publishDate2,desc",
  publishOrder3: "publishDate3,desc",
  //箭头方向	1：升许；2：降序
  companyCodeNum: 1,
  publishNum0: "",
  publishNum1: "",
  publishNum2: "",
  publishNum3: "",
  actualDateNum: "",
  reportType: [], //报告类型数据
  init: function () {
    this.loadEvents();
  },
  loadEvents: function () {
    var _this = this;
    $(".js_date input").attr("placeholder", "实际披露日");
    $(".js_periodic .table-responsive").before(
      '<p class="table_tip"><font color="red">提示：</font>点击公司代码、首次预约日、变更日、实际披露日可以排序，点击实际披露日期可查看公告</p>'
    );
    _this.getSelectValue();
    //日期范围渲染
    laydate({
      elem: ".js_date input",
      theme: "#b50005",
      format: "yyyy-MM-dd",
      min: "1990-12-19",
      max: get_systemDate_global(),
      trigger: "click",
      btns: ["clear", "confirm"],

      done: function (value, date, endDate) {
        //选择时间触发查询
        setTimeout(function () {
          _this.setPeriodicParams();
        }, 500);
      },
    });
    triggerSearch(_this.setPeriodicParams); //点击搜索、回车触发查询
    //排序
    $(".js_periodic").on("click", ".js_orderBtn", function () {
      var orderValue = $(this).attr("data-order").split(",");
      _this.periodicParams.order = orderValue[0] + "|" + orderValue[1];
      //初始化所有排序字段
      _this.companyOrder = "companyCode,desc";
      _this.actualDateOrder = "actualDate,desc";
      _this.publishOrder0 = "publishDate0,desc";
      _this.publishOrder1 = "publishDate1,desc";
      _this.publishOrder2 = "publishDate2,desc";
      _this.publishOrder3 = "publishDate3,desc";
      _this.companyCodeNum = "";
      _this.publishNum0 = "";
      _this.publishNum1 = "";
      _this.publishNum2 = "";
      _this.publishNum3 = "";
      _this.actualDateNum = "";
      //判断点击的排序字段修改值并修改箭头方向
      switch (orderValue[0]) {
        case "companyCode":
          if (orderValue[1] == "desc") {
            _this.companyOrder = "companyCode,asc";
            _this.companyCodeNum = 2;
          } else {
            _this.companyOrder = "companyCode,desc";
            _this.companyCodeNum = 1;
          }
          break;
        case "publishDate0":
          if (orderValue[1] == "desc") {
            _this.publishOrder0 = "publishDate0,asc";
            _this.publishNum0 = 2;
          } else {
            _this.publishOrder0 = "publishDate0,desc";
            _this.publishNum0 = 1;
          }
          break;
        case "publishDate1":
          if (orderValue[1] == "desc") {
            _this.publishOrder1 = "publishDate1,asc";
            _this.publishNum1 = 2;
          } else {
            _this.publishOrder1 = "publishDate1,desc";
            _this.publishNum1 = 1;
          }
          break;
        case "publishDate2":
          if (orderValue[1] == "desc") {
            _this.publishOrder2 = "publishDate2,asc";
            _this.publishNum2 = 2;
          } else {
            _this.publishOrder2 = "publishDate2,desc";
            _this.publishNum2 = 1;
          }
          break;
        case "publishDate3":
          if (orderValue[1] == "desc") {
            _this.publishOrder3 = "publishDate3,asc";
            _this.publishNum3 = 2;
          } else {
            _this.publishOrder3 = "publishDate3,desc";
            _this.publishNum3 = 1;
          }
          break;
        case "actualDate":
          if (orderValue[1] == "desc") {
            _this.actualDateOrder = "actualDate,asc";
            _this.actualDateNum = 2;
          } else {
            _this.actualDateOrder = "actualDate,desc";
            _this.actualDateNum = 1;
          }
          break;
      }
      _this.setPeriodicParams();
    });
  },
  //获取下拉框数据
  getSelectValue: function () {
    var _this = this;
    getJSONP({
      type: "post",
      dataType: "jsonp",
      url: sseQueryURL + "commonQuery.do",
      data: {
        sqlId: "SSE_PL_SSGSXX_DQBGYYQK_LX_L",
      },
      successCallback: function (data) {
        $.each(data.result, function (k, v) {
          _this.reportType.push({
            value: v.BULLETIN_TYPE,
            name: v.TYPE,
          });
        });
        //下拉框添加数据
        bootstrapSelect({
          method: function () {
            //报告类型渲染下拉框
            $(".js_reportType .selectpicker")
              .html(addSelectOption(_this.reportType))
              .selectpicker("refresh")
              .selectpicker("render");
            //报告类型改变触发查询
            $(".js_reportType .selectpicker").on(
              "changed.bs.select",
              function (e) {
                _this.setPeriodicParams();
              }
            );
          },
        });
        //报告类型赋初始值
        _this.periodicParams.bulletintype = data.result[0].BULLETIN_TYPE;
        _this.periodicParams.publishYear = data.result[0].PUBLISH_YEAR;
        _this.getPeriodicList(1);
      },
    });
  },
  setPeriodicParams: function () {
    var _this = periodic;

    _this.periodicParams.companyCode = $("#inputCode").val(); //证券代码
    _this.periodicParams.bulletintype = $(".js_reportType .selectpicker").val(); //报告类型
    _this.periodicParams.publishYear = $(
      ".js_reportType .filter-option-inner-inner"
    )
      .text()
      .trim()
      .substring(0, 4); //年份
    _this.periodicParams.startTime = $(".js_date input").val(); //实际披露日
    if (
      _this.periodicParams.startTime < "1990-12-19" &&
      _this.periodicParams.startTime != ""
    ) {
      bootstrapModal({
        text: "您选择的日期超出检索范围，请重输。",
      });
    } else if (
      isNaN(_this.periodicParams.companyCode) &&
      _this.periodicParams.companyCode != ""
    ) {
      bootstrapModal({
        text: "证券代码必须为6位数字，请根据智能提示选择证券代码后查询",
      });
    } else if (
      _this.periodicParams.companyCode.length != 6 &&
      _this.periodicParams.companyCode != ""
    ) {
      bootstrapModal({
        text: "证券代码必须为6位数字",
      });
    } else {
      _this.getPeriodicList(1);
    }
  },
  getPeriodicList: function (pageIndex) {
    var _this = this;
    if (!paginationChange(_this.periodicParams, pageIndex)) {
      //触发分页改变分页参数
      return;
    }
    var emptyTr = '<tr><td colspan="9">暂无数据</td></tr>';
    var periodicHtml = "<thead><tr>";
    periodicHtml +=
      '<th class="js_orderBtn text-nowrap" style="width:100px" data-order="' +
      _this.companyOrder +
      '">公司代码<span class="sort_btn"><em class="caret_up ' +
      (_this.companyCodeNum == 1 ? "fill" : "") +
      '"></em><em class="caret_down ' +
      (_this.companyCodeNum == 2 ? "fill" : "") +
      '"></em></span></th>';
    periodicHtml += "<th>公司简称</th>";
    periodicHtml += '<th class="text-nowrap">报告类型</th>';
    periodicHtml += '<th class="text-nowrap">报告年度</th>';
    periodicHtml +=
      '<th class="js_orderBtn text-nowrap" data-order="' +
      _this.publishOrder0 +
      '">首次预约日<span class="sort_btn"><em class="caret_up ' +
      (_this.publishNum0 == 1 ? "fill" : "") +
      '"></em><em class="caret_down ' +
      (_this.publishNum0 == 2 ? "fill" : "") +
      '"></em></span></th>';
    periodicHtml +=
      '<th class="js_orderBtn text-nowrap" data-order="' +
      _this.publishOrder1 +
      '">一次变更日<span class="sort_btn"><em class="caret_up ' +
      (_this.publishNum1 == 1 ? "fill" : "") +
      '"></em><em class="caret_down ' +
      (_this.publishNum1 == 2 ? "fill" : "") +
      '"></em></span></th>';
    periodicHtml +=
      '<th class="js_orderBtn text-nowrap" data-order="' +
      _this.publishOrder2 +
      '">二次变更日<span class="sort_btn"><em class="caret_up ' +
      (_this.publishNum2 == 1 ? "fill" : "") +
      '"></em><em class="caret_down ' +
      (_this.publishNum2 == 2 ? "fill" : "") +
      '"></em></span></th>';
    periodicHtml +=
      '<th class="js_orderBtn text-nowrap" data-order="' +
      _this.publishOrder3 +
      '">三次变更日<span class="sort_btn"><em class="caret_up ' +
      (_this.publishNum3 == 1 ? "fill" : "") +
      '"></em><em class="caret_down ' +
      (_this.publishNum3 == 2 ? "fill" : "") +
      '"></em></span></th>';
    periodicHtml +=
      '<th class="js_orderBtn text-nowrap" data-order="' +
      _this.actualDateOrder +
      '">实际披露日<span class="sort_btn"><em class="caret_up ' +
      (_this.actualDateNum == 1 ? "fill" : "") +
      '"></em><em class="caret_down ' +
      (_this.actualDateNum == 2 ? "fill" : "") +
      '"></em></span></th>';
    periodicHtml += "</tr></thead><tbody>";
    getJSONP({
      type: "post",
      dataType: "jsonp",
      url: _this.periodicUrl,
      data: _this.periodicParams,
      successCallback: function (data) {
        if (data && data.result && data.result.length > 0) {
          $.each(data.result, function (k, v) {
            var reportT = "";
            var publishDate0,
              publishDate1,
              publishDate2,
              publishDate3,
              actualDate;
            switch (v.bulletinType) {
              case "L013":
                reportT = "第一季度季报";
                break;
              case "L011":
                reportT = "年报";
                break;
              case "L014":
                reportT = "第三季度季报";
                break;
              case "L012":
                reportT = "半年报<br />（中报）";
                break;
            }
            if (v.publishDate0 == null || v.publishDate0 == "") {
              publishDate0 = "-";
            } else {
              publishDate0 = v.publishDate0;
            }
            if (v.publishDate1 == null || v.publishDate1 == "") {
              publishDate1 = "-";
            } else {
              publishDate1 = v.publishDate1;
            }
            if (v.publishDate2 == null || v.publishDate2 == "") {
              publishDate2 = "-";
            } else {
              publishDate2 = v.publishDate2;
            }
            if (v.publishDate3 == null || v.publishDate3 == "") {
              publishDate3 = "-";
            } else {
              publishDate3 = v.publishDate3;
            }
            if (v.actualDate == null || v.actualDate == "") {
              actualDate = "<td>-</td>";
            } else {
              actualDate =
                '<td><a href="/disclosure/listedinfo/regular/index.shtml?productId=' +
                v.companyCode +
                '" target="_blank">' +
                v.actualDate +
                "</a></td>";
            }
            periodicHtml += "<tr>";
            periodicHtml +=
              '<td class="codeNameWidth "><a target="_blank" href="/assortment/stock/list/info/company/index.shtml?COMPANY_CODE=' +
              v.companyCode +
              '">' +
              v.companyCode +
              "</a></td>";
            periodicHtml +=
              '<td class="codeNameWidth "><span>' +
              v.companyAbbr +
              "</span></td>"; //公司简称
            periodicHtml += '<td class="text-nowrap">' + reportT + "</td>"; //报告类型
            periodicHtml +=
              '<td class="text-nowrap">' + v.publishYear + "</td>"; //报告年度
            periodicHtml += '<td class="text-nowrap">' + publishDate0 + "</td>"; //首次预约日
            periodicHtml += '<td class="text-nowrap">' + publishDate1 + "</td>"; //一次变更日
            periodicHtml += '<td class="text-nowrap">' + publishDate2 + "</td>"; //二次变更日
            periodicHtml += '<td class="text-nowrap">' + publishDate3 + "</td>"; //三次变更日
            periodicHtml += actualDate; //实际披露日
            periodicHtml += "</tr>";
          });
          periodicHtml += "</tbody>";
          $(".js_periodic .table").html(periodicHtml);
          //调用分页
          Page.navigation(
            ".js_periodic .pagination-box",
            data.pageHelp.pageCount,
            data.pageHelp.total,
            data.pageHelp.pageNo,
            data.pageHelp.pageSize,
            "periodic.getPeriodicList"
          );
        } else {
          periodicHtml += emptyTr;
          periodicHtml += "</tbody>";
          $(".js_periodic .table").html(periodicHtml);
          $(".js_periodic .pagination-box").html("");
        }
        //搜索代码添加cookie
        popularize.saveCpyIntoCookie(
          $("#inputCode").val().trim(),
          $("#inputCode"),
          1
        );
      },
      errCallback: function () {
        periodicHtml += emptyTr;
        periodicHtml += "</tbody>";
        $(".js_periodic .table").html(periodicHtml);
        $(".js_periodic .pagination-box").html("");
      },
    });
  },
};
if ($(".js_periodic").length > 0) {
  periodic.init();
}
//定期报告预约情况end

/**
 * 定期报告
 */
var regular = {
  regularUrl: sseQueryURL + "security/stock/queryCompanyBulletin.do", //定期报告url
  queryProductId: "", //接收证券代码参数
  todayDate: get_systemDate_global(),
  tomorrowDay: "", //下一天日期
  //定期报告参数
  regularParams: {
    isPagination: true,
    "pageHelp.pageSize": 25,
    "pageHelp.pageNo": 1,
    "pageHelp.beginPage": 1,
    "pageHelp.cacheSize": 1,
    "pageHelp.endPage": 1,
    productId: "", //证券代码
    securityType: "0101,120100,020100,020200,120200", //板块类型
    reportType2: "DQBG", //定期报告
    reportType: "ALL", //报告类型
    beginDate: "", //开始日期
    endDate: "", //结束日期
  },
  //板块数据
  plateOption: [
    {
      value: "0101,120100,020100,020200,120200",
      name: "全部板块",
    },
    {
      value: "0101",
      name: "主板",
    },
    {
      value: "120100,020100,020200,120200",
      name: "科创板",
    },
  ],
  //报告类型数据
  reportTypeOption: [
    {
      value: "ALL",
      name: "全部",
    },
    {
      value: "YEARLY",
      name: "年报",
    },
    {
      value: "QUATER1",
      name: "第一季度报",
    },
    {
      value: "QUATER2",
      name: "半年报",
    },
    {
      value: "QUATER3",
      name: "第三季度报",
    },
  ],
  init: function () {
    this.loadEvents();
  },
  loadEvents: function () {
    var _this = this;
    bootstrapSelect({
      method: function () {
        //板块数据渲染
        $(".js_plate .selectpicker")
          .html(addSelectOption(_this.plateOption))
          .selectpicker("refresh")
          .selectpicker("render");
        //报告类型数据渲染
        $(".js_reportType .selectpicker")
          .html(addSelectOption(_this.reportTypeOption))
          .selectpicker("refresh")
          .selectpicker("render");

        //下拉框改变触发查询
        $(".js_plate .selectpicker").on("changed.bs.select", function (e) {
          _this.setRegularParams();
        });
        //下拉框改变触发查询
        $(".js_reportType .selectpicker").on("changed.bs.select", function (e) {
          _this.setTypeParams();
        });
      },
    });
    //日期范围渲染
    laydate({
      elem: ".js_dateRange input",
      theme: "#b50005",
      format: "yyyy-MM-dd",
      range: true,
      min: "1990-12-19",
      trigger: "click",
      btns: ["confirm"],
      done: function (value, date, endDate) {
        //选择时间触发查询
        setTimeout(function () {
          _this.setRegularParams();
        }, 500);
      },
    });
    //获取第二天日期
    _this.tomorrowDay = changeFormatDate(_this.todayDate, 1, 0, 0);
    //接收证券代码参数
    _this.queryProductId = getWindowHref().productId;
    //有证券代码参数时
    if (_this.queryProductId && _this.queryProductId != "undefined") {
      _this.regularParams.productId = _this.queryProductId;
      //证券代码输入框赋值
      _this.regularParams.productId = _this.queryProductId;
      $("#inputCode").val(_this.queryProductId);
      //日期框赋值
      $(".js_dateRange input").val(
        changeFormatDate(_this.tomorrowDay, 0, -3, 0) +
          " - " +
          _this.tomorrowDay
      );
      _this.regularParams.beginDate = changeFormatDate(
        _this.tomorrowDay,
        0,
        -3,
        0
      );
      _this.regularParams.endDate = _this.tomorrowDay;
      //调用接口
      _this.getRegularList(1);
    } else {
      //无默认证券代码时
      _this.regularParams.productId = "";
      //添加默认日期范围
      _this.regularParams.beginDate = changeFormatDate(
        _this.tomorrowDay,
        0,
        -3,
        0
      );
      _this.regularParams.endDate = _this.tomorrowDay;
      _this.getRegularList(1);
    }
    //点击搜索、回车触发查询
    triggerSearch(_this.setRegularParams);
  },
  //选择报告类型无限制条件
  setTypeParams: function () {
    var _this = regular;
    _this.regularParams.productId = $("#inputCode").val(); //证券代码
    _this.regularParams.securityType = $(".js_plate .selectpicker").val(); //板块类型
    _this.regularParams.reportType = $(".js_reportType .selectpicker").val(); //报告类型
    _this.regularParams.beginDate = $(".js_dateRange input")
      .val()
      .substr(0, 10); //开始时间
    _this.regularParams.endDate = $(".js_dateRange input").val().substr(-10); //结束时间
    _this.getRegularList(1);
  },
  setRegularParams: function () {
    var _this = regular;
    _this.regularParams.productId = $("#inputCode").val(); //证券代码
    _this.regularParams.securityType = $(".js_plate .selectpicker").val(); //板块类型
    _this.regularParams.reportType = $(".js_reportType .selectpicker").val(); //报告类型
    _this.regularParams.beginDate = $(".js_dateRange input")
      .val()
      .substr(0, 10); //开始时间
    _this.regularParams.endDate = $(".js_dateRange input").val().substr(-10); //结束时间
    //代码时间全为空
    if (
      _this.regularParams.productId == "" &&
      _this.regularParams.beginDate == ""
    ) {
      bootstrapModal({
        text: "请您指定证券代码或日期后再进行查询",
      });
      //代码不为空，时间为空默认添加近三月时间
    } else if (
      _this.regularParams.productId != "" &&
      _this.regularParams.beginDate == ""
    ) {
      $(".js_dateRange input").val(
        changeFormatDate(_this.tomorrowDay, 0, -3, 0) +
          " - " +
          _this.tomorrowDay
      );
      _this.regularParams.beginDate = $(".js_dateRange input")
        .val()
        .substr(0, 10); //开始时间
      _this.regularParams.endDate = $(".js_dateRange input").val().substr(-10); //结束时间
      //调用接口
      _this.getRegularList(1);
      //代码为空，时间不为空
    } else if (
      _this.regularParams.productId == "" &&
      _this.regularParams.beginDate != ""
    ) {
      if (_this.regularParams.beginDate > _this.regularParams.endDate) {
        bootstrapModal({
          text: "开始时间不能大于结束时间！",
        });
        return;
      }
      if (
        !IsDayLimit(
          _this.regularParams.beginDate,
          _this.regularParams.endDate,
          30,
          0,
          0
        )
      ) {
        bootstrapModal({
          text: "您未指定证券代码，查询将只提供日期间隔不超过30天的公告",
        });
      } else {
        //调用接口
        _this.getRegularList(1);
      }
      //代码时间都不为空
    } else if (
      _this.regularParams.productId != "" &&
      _this.regularParams.beginDate != ""
    ) {
      if (_this.regularParams.beginDate > _this.regularParams.endDate) {
        bootstrapModal({
          text: "开始时间不能大于结束时间！",
        });
        return;
      }
      if (
        !IsDayLimit(
          _this.regularParams.beginDate,
          _this.regularParams.endDate,
          0,
          0,
          3
        )
      ) {
        bootstrapModal({
          text: "查询只提供日期间隔不超过3年的公告",
        });
      } else {
        //调用接口
        _this.getRegularList(1);
      }
    }
  },
  getRegularList: function (pageIndex) {
    var _this = this;
    if (!paginationChange(_this.regularParams, pageIndex)) {
      //触发分页改变分页参数
      return;
    }
    
    //gio定期报告筛选埋点
    var _sseMarketType_var = "";
    if (_this.regularParams.securityType == "0101,120100,020100,020200,120200") {
      _sseMarketType_var = "全部";
    } else if (_this.regularParams.securityType == "0101") {
      _sseMarketType_var = "主板";
    } else if (_this.regularParams.securityType == "120100,020100,020200,120200") {
      _sseMarketType_var = "科创板";
    }
    var _sseReportType_var = "";
    if (_this.regularParams.reportType == "ALL") {
      _sseReportType_var = "全部";
    } else if (_this.regularParams.reportType == "YEARLY") {
      _sseReportType_var = "年报";
    } else if (_this.regularParams.reportType == "QUATER1") {
      _sseReportType_var = "第一季度报";
    } else if (_this.regularParams.reportType == "QUATER2") {
      _sseReportType_var = "半年报";
    } else if (_this.regularParams.reportType == "QUATER3") {
      _sseReportType_var = "第三季度报";
    }
    gdp("track", "sseRegularReportClick", {
      sseSecurityCode_var: _this.regularParams.productId,
      sseMarketType_var: _sseMarketType_var,
      sseReportType_var: _sseReportType_var,
      sseStartDate_var: _this.regularParams.beginDate,
      sseEndDate_var: _this.regularParams.endDate,
    });

    var emptyTr = '<tr><td colspan="4">暂无数据</td></tr>';
    var regularHtml = "<thead><tr>";
    regularHtml += "<th>证券代码</th>";
    regularHtml += "<th>证券简称</th>";
    regularHtml += "<th>公告标题</th>";
    regularHtml += "<th>公告时间</th>";
    regularHtml += "</tr></thead><tbody>";
    getJSONP({
      type: "post",
      dataType: "jsonp",
      url: _this.regularUrl,
      data: _this.regularParams,
      successCallback: function (data) {
        if (data && data.result && data.result.length > 0) {
          $.each(data.result, function (k, v) {
            regularHtml += "<tr>";
            regularHtml +=
              '<td class="codeNameWidth"><span>' +
              v.SECURITY_CODE +
              "</span></td>"; //证券代码
            regularHtml +=
              '<td class="codeNameWidth"><span>' +
              (v.SECURITY_NAME && v.SECURITY_NAME.toLowerCase() != "null"
                ? v.SECURITY_NAME
                : "-") +
              "</span></td>"; //证券简称
            regularHtml +=
              '<td><a class="table_titlewrap" href="' +
              v.URL +
              '" target="_blank"><span onclick="clickRegularPdf($(this))">' +
              v.TITLE +
              "</span></a></td>"; //标题
            regularHtml += '<td class="text-nowrap">' + v.SSEDATE + "</td>"; //时间
            regularHtml += "<tr>";
          });
          regularHtml += "</tbody>";
          $(".js_regular .table").html(regularHtml);
          //调用分页
          Page.navigation(
            ".js_regular .pagination-box",
            data.pageHelp.pageCount,
            data.pageHelp.total,
            data.pageHelp.pageNo,
            data.pageHelp.pageSize,
            "regular.getRegularList"
          );
        } else {
          regularHtml += emptyTr;
          regularHtml += "</tbody>";
          $(".js_regular .table").html(regularHtml);
          $(".js_regular .pagination-box").html("");
        }
        //搜索代码添加cookie
        popularize.saveCpyIntoCookie(
          $("#inputCode").val().trim(),
          $("#inputCode"),
          1
        );
      },
      errCallback: function () {
        regularHtml += emptyTr;
        regularHtml += "</tbody>";
        $(".js_regular .table").html(regularHtml);
        $(".js_regular .pagination-box").html("");
      },
    });
  },
};
if ($(".js_regular").length > 0) {
  regular.init();
}

//gio定期报告pdf点击事件埋点
function clickRegularPdf (t) {
  gdp("track", "sseRegularReportClick", {
    sseCheckPdf_var: t.text(),
  });
}
//定期报告end

/**
 * 公告摘要
 */
var summaries = {
  summariesUrl: sseQueryURL + "infodisplay/queryBulletinSummary.do", //公告摘要url
  summariesParams: {
    isPagination: true,
    "pageHelp.pageSize": 25,
    "pageHelp.pageNo": 1,
    "pageHelp.beginPage": 1,
    "pageHelp.cacheSize": 1,
    "pageHelp.endPage": 1,
    productType: 1,
  },
  init: function () {
    this.loadEvents();
    this.getSummariesList(1, true);
  },
  loadEvents: function () {
    var _this = this;
    //日期范围渲染
    laydate({
      elem: ".js_dateRange input",
      theme: "#b50005",
      format: "yyyy-MM-dd",
      range: true,
      min: "1990-12-19",
      trigger: "click",
      btns: ["confirm"],
      done: function (value, date, endDate) {
        //选择时间触发查询
        setTimeout(function () {
          _this.setSummariesParams();
        }, 500);
      },
    });
    triggerSearch(_this.setSummariesParams);
  },
  setSummariesParams: function () {
    var _this = summaries;
    //获取证券代码
    _this.summariesParams.InputCond = $("#inputCode").val()
      ? $("#inputCode").val()
      : "";
    //获取日期
    _this.summariesParams.dateDeclareStart = $(".js_dateRange input")
      .val()
      .substr(0, 10)
      ? $(".js_dateRange input").val().substr(0, 10)
      : ""; //开始日期
    _this.summariesParams.dateDeclareEnd = $(".js_dateRange input")
      .val()
      .substr(-10)
      ? $(".js_dateRange input").val().substr(-10)
      : ""; //结束日期
    if (
      isNaN(_this.summariesParams.InputCond) &&
      _this.summariesParams.InputCond != ""
    ) {
      bootstrapModal({
        text: "证券代码必须为6位数字，请根据智能提示选择证券代码后查询",
      });
      return;
    } else if (
      _this.summariesParams.InputCond.length != 6 &&
      _this.summariesParams.InputCond != ""
    ) {
      bootstrapModal({
        text: "证券代码必须为6位数字",
      });
      return;
    }
    if (
      _this.summariesParams.dateDeclareStart >
      _this.summariesParams.dateDeclareEnd
    ) {
      bootstrapModal({
        text: "开始日期不能大于结束日期",
      });
      return;
    }
    //调用接口
    _this.getSummariesList(1);
  },
  getSummariesList: function (pageIndex, isFirst) {
    var _this = this;
    if (!paginationChange(_this.summariesParams, pageIndex)) {
      //修改分页参数
      return;
    }
    var emptyTr = '<li class="list-group-item">暂无数据</li>';
    var summariesHtml = "";
    getJSONP({
      type: "post",
      dataType: "jsonp",
      url: _this.summariesUrl,
      data: _this.summariesParams,
      successCallback: function (data) {
        if (data && data.result && data.result.length > 0) {
          $.each(data.result, function (k, v) {
            summariesHtml +=
              '<li class="list-group-item"><a href="/disclosure/listedinfo/summaries/indexDetail.shtml?FLAG=NEW&SEQ=' +
              v.seq +
              '" target="_blank">' +
              v.bulletinTitle +
              '</a><span class="new_date">' +
              v.dateDeclare +
              "</span></li>";
          });
          $(".js_summaries .list-group").html(summariesHtml);
          //调用分页
          Page.navigation(
            ".js_summaries .pagination-box",
            data.pageHelp.pageCount,
            data.pageHelp.total,
            data.pageHelp.pageNo,
            data.pageHelp.pageSize,
            "summaries.getSummariesList"
          );

          //第一次加载时填充日期
          if (isFirst) {
            $(".js_dateRange input").val(
              data.result[0].dateDeclare + " - " + data.result[0].dateDeclare
            );
          }
        } else {
          $(".js_summaries .list-group").html(emptyTr);
          $(".js_summaries .pagination-box").html("");
        }
        //搜索代码添加cookie
        popularize.saveCpyIntoCookie(
          $("#inputCode").val().trim(),
          $("#inputCode"),
          1
        );
      },
      errCallback: function () {
        $(".js_summaries .list-group").html(emptyTr);
        $(".js_summaries .pagination-box").html("");
      },
    });
  },
};
if ($(".js_summaries").length > 0) {
  summaries.init();
}
//公告摘要end

/**
 * 公告摘要详情
 */
var announcementSumDetail = {
  init: function () {
    this.loadEvents();
  },
  loadEvents: function () {
    var _this = this;
    var seq = getWindowHref().SEQ;
    var $noticPickDetail = $(".js_announcementSum");
    if (seq != null && seq != undefined) {
      $.ajax({
        url: sseQueryURL + "infodisplay/queryBulletinSummaryPopup.do",
        type: "post",
        dataType: "jsonp",
        jsonp: "jsonCallBack",
        jsonpCallback:
          "jsonpCallback" + Math.floor(Math.random() * (100000 + 1)),
        data: {
          seq: seq,
          flag: "NEW",
        },
        success: function (callBackData) {
          if (
            callBackData.result[0] != null &&
            callBackData.result[0] != undefined
          ) {
            $noticPickDetail
              .find("h2")
              .html(callBackData.result[0].bulletinTitle);
            $noticPickDetail
              .find(".article_opt")
              .find("i")
              .html(callBackData.result[0].dateDeclare);
            var text_content = "";
            if (
              callBackData.result[0].bulletinContent.indexOf("http://") > -1
            ) {
              text_content =
                "<pre>" +
                callBackData.result[0].bulletinContent.substring(
                  0,
                  callBackData.result[0].bulletinContent.indexOf("http://")
                );
              text_content +=
                '<a href="' +
                callBackData.result[0].bulletinContent.substring(
                  callBackData.result[0].bulletinContent.indexOf("http://"),
                  callBackData.result[0].bulletinContent.length
                ) +
                '" target="_blank">' +
                callBackData.result[0].bulletinContent.substring(
                  callBackData.result[0].bulletinContent.indexOf("http://"),
                  callBackData.result[0].bulletinContent.length
                ) +
                "</a>";
              text_content += "</pre>";
            } else {
              text_content =
                "<pre>" + callBackData.result[0].bulletinContent + "</pre>";
            }
            $noticPickDetail.find("p").html(text_content);
            _this.doMoreGGZY(
              callBackData.result[0].bulletinTitle,
              callBackData.result[0].bulletinTitle
            );
          } else {
            $.ajax({
              url: sseQueryURL + "infodisplay/queryBulletinSummaryPopup.do",
              type: "post",
              dataType: "jsonp",
              jsonp: "jsonCallBack",
              jsonpCallback:
                "jsonpCallback" + Math.floor(Math.random() * (100000 + 1)),
              data: {
                seq: seq,
                flag: "",
              },
              success: function (callBackData) {
                if (
                  callBackData.result[0] != null &&
                  callBackData.result[0] != undefined
                ) {
                  $noticPickDetail
                    .find("h2")
                    .html(callBackData.result[0].bulletinTitle);
                  $noticPickDetail
                    .find(".article_opt")
                    .find("i")
                    .html(callBackData.result[0].dateDeclare);
                  var text_content = "";
                  if (
                    callBackData.result[0].bulletinContent.indexOf("http://") >
                    -1
                  ) {
                    text_content =
                      "<pre>" +
                      callBackData.result[0].bulletinContent.substring(
                        0,
                        callBackData.result[0].bulletinContent.indexOf(
                          "http://"
                        )
                      );
                    text_content +=
                      '<a href="' +
                      callBackData.result[0].bulletinContent.substring(
                        callBackData.result[0].bulletinContent.indexOf(
                          "http://"
                        ),
                        callBackData.result[0].bulletinContent.length
                      ) +
                      '" target="_blank">' +
                      callBackData.result[0].bulletinContent.substring(
                        callBackData.result[0].bulletinContent.indexOf(
                          "http://"
                        ),
                        callBackData.result[0].bulletinContent.length
                      ) +
                      "</a>";
                    text_content += "</pre>";
                  } else {
                    text_content =
                      "<pre>" +
                      callBackData.result[0].bulletinContent +
                      "</pre>";
                  }
                  $noticPickDetail.find("p").html(text_content);
                  _this.doMoreGGZY(
                    callBackData.result[0].bulletinTitle,
                    callBackData.result[0].bulletinTitle
                  );
                }
              },
            });
          }
        },
      });
    }
  },
  doMoreGGZY: function (title, date) {
    var _this = this;
    if (title != null && title != undefined) {
      //ajax请求
      var htmlArrFir = [];
      htmlArrFir.push("<dl>");
      htmlArrFir.push("<dd>数据加载中......</dd>");
      htmlArrFir.push("</dl>");
      $(".sse_list_1").html(htmlArrFir.join(""));
      if (title != "" && title != undefined) {
        var resultTitle = title;
        if (resultTitle != "") {
          $.ajax({
            url: sseQueryURL + "search/getSearchResult.do",
            type: "post",
            dataType: "jsonp",
            jsonp: "jsonCallBack",
            jsonpCallback:
              "jsonpCallback" + Math.floor(Math.random() * (100000 + 1)),
            data: {
              search: "qwjs",
              perpage: 10,
              orderby: "-CRELEASETIME",
              searchword: resultTitle.substring(8),
            },
            success: function (callBackData) {
              _this.doShowGGZYTitleAjaxEx(callBackData);
            },
          });
        }
      }
    }
  },
  doShowGGZYTitleAjaxEx: function (callBackData) {
    var htmlArr = [];
    var returnData = callBackData.data;
    if (returnData == undefined || returnData.length < 1) {
      htmlArr.push("<dl>");
      htmlArr.push("<dd>暂无数据</dd>");
      htmlArr.push("</dl>");
    } else {
      htmlArr.push("<dl>");
      for (var i = 0; i < returnData.length; ++i) {
        if (i > 4) {
          break;
        } else {
          var data = returnData[i];
          htmlArr.push("<dd>");
          htmlArr.push("<span>" + data.CRELEASETIME + "</span>");
          htmlArr.push(
            '<a href="' +
              data.CURL +
              '" target="_blank">' +
              data.CTITLE_TXT +
              "</a>"
          );
          htmlArr.push("</dd>");
        }
      }
      htmlArr.push("</dl>");
    }
    $(".sse_list_1").html(htmlArr.join(""));
  },
};
if ($(".js_announcementSum").length > 0) {
  announcementSumDetail.init();
}

/**
 * 风险警示板
 */
var riskplate = {
  riskplateUrl: sseQueryURL + "commonSoaQuery.do", //风险警示板url
  init: function () {
    if ($(".js_fxjs").length > 0) {
      this.getRiskplateList(".js_fxjs .table", "S", "0"); //风险警示股票
    }
    if ($(".js_tszl").length > 0) {
      this.getRiskplateList(".js_tszl .table", "P", "0"); //退市整理股票
    }
    if ($(".js_starfxjs").length > 0) {
      this.getRiskplateList(".js_starfxjs .table", "S", "1"); //科创板风险警示
    }
  },
  getRiskplateList: function (elem, domesticIndicator, productType) {
    var _this = this;
    var emptyTr = '<tr><td colspan="2">暂无数据</td></tr>';
    var riskplateHtml = "<thead><tr>";
    riskplateHtml += "<th>证券代码</th>";
    riskplateHtml += "<th>证券简称</th>";
    riskplateHtml += "</tr></thead><tbody>";
    getJSONP({
      type: "post",
      dataType: "jsonp",
      url: _this.riskplateUrl,
      data: {
        sqlId: "PL_SSGSXX_FXJSBGPLB",
        domesticIndicator: domesticIndicator,
        productType: productType,
      },
      successCallback: function (data) {
        if (data && data.result && data.result.length > 0) {
          $.each(data.result, function (k, v) {
            riskplateHtml += "<tr>";
            riskplateHtml +=
              '<td><a href="/assortment/stock/list/info/company/index.shtml?COMPANY_CODE=' +
              v.INSTRUMENT_ID +
              '" target="_blank">' +
              v.INSTRUMENT_ID +
              "</a></td>";
            riskplateHtml +=
              '<td><a href="/assortment/stock/list/info/company/index.shtml?COMPANY_CODE=' +
              v.INSTRUMENT_ID +
              '" target="_blank">' +
              v.INSTRUMENT_SHORT +
              "</a></td>";
            riskplateHtml += "</tr>";
          });
          riskplateHtml += "</tbody>";
          $(elem).html(riskplateHtml);
        } else {
          riskplateHtml += emptyTr;
          riskplateHtml += "</tbody>";
          $(elem).html(riskplateHtml);
        }
      },
      errCallback: function () {
        riskplateHtml += emptyTr;
        riskplateHtml += "</tbody>";
        $(elem).html(riskplateHtml);
      },
    });
  },
};
if ($(".js_riskplate").length > 0) {
  riskplate.init();
}
//风险警示板end

/**
 * 科创板风险警示
 */
var kcbriskplate = {
  kcbriskplateUrl: sseQueryURL + "commonSoaQuery.do", //科创板风险警示url
  init: function () {
    if ($(".js_fxjs").length > 0) {
      this.getKcbRiskplateList(".js_fxjs .table", "0"); //风险警示股票
    }
    if ($(".js_tszl").length > 0) {
      this.getKcbRiskplateList(".js_tszl .table", "1"); //退市整理股票
    }
  },
  getKcbRiskplateList: function (elem, type) {
    var _this = this;
    var emptyTr = '<tr><td colspan="2">暂无数据</td></tr>';
    var kcbriskplateHtml = "<thead><tr>";
    kcbriskplateHtml += "<th>证券代码</th>";
    kcbriskplateHtml += "<th>证券简称</th>"; 
    kcbriskplateHtml += "</tr></thead><tbody>";
    getJSONP({
      type: "post",
      dataType: "jsonp",
      url: _this.kcbriskplateUrl,
      data: {
        sqlId: "SSE_PL_SSGSXX_KCBFXTS_L",
        type: type,
      },
      successCallback: function (data) {
        if (data && data.result && data.result.length > 0) {
          $.each(data.result, function (k, v) {
            if (v.secCode.substr(0, 3) == "688") {
              kcbriskplateHtml += "<tr>";
              kcbriskplateHtml +=
                '<td> '+ v.secCode +'</td>';
              kcbriskplateHtml +=
                '<td> '+v.secNameCn+'</td>';
              kcbriskplateHtml += "</tr>";
            }
          });
          kcbriskplateHtml += "</tbody>";
          $(elem).html(kcbriskplateHtml);
        } else {
          kcbriskplateHtml += emptyTr;
          kcbriskplateHtml += "</tbody>";
          $(elem).html(kcbriskplateHtml);
        }
      },
      errCallback: function () {
        kcbriskplateHtml += emptyTr;
        kcbriskplateHtml += "</tbody>";
        $(elem).html(kcbriskplateHtml);
      },
    });
  },
};
if ($(".js_kcbriskplate").length > 0) {
  kcbriskplate.init();
}
//科创板风险警示end
