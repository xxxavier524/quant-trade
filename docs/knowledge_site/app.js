/* AlphaPulse 知识库 — 共享脚本：侧边栏导航 / 进度 / 测验判分 / 术语tooltip / 翻页 */
(function () {
  "use strict";

  var AP_CHAPTERS = [
    { file: "index.html",       num: "00",   title: "总览与学习路径", level: "" },
    { file: "l1-factors.html",  num: "L1·1", title: "因子与 IC",             level: "L1 量化基础" },
    { file: "l1-backtest.html", num: "L1·2", title: "回测与过拟合",          level: "L1 量化基础" },
    { file: "l1-winrate.html",  num: "L1·3", title: "胜率、赔率与期望",      level: "L1 量化基础" },
    { file: "l2-scoring.html",  num: "L2·1", title: "多因子评分体系",        level: "L2 经典方法" },
    { file: "l2-params.html",   num: "L2·2", title: "参数稳健性与网格搜索",  level: "L2 经典方法" },
    { file: "l2-position.html", num: "L2·3", title: "仓位与组合管理",        level: "L2 经典方法" },
    { file: "l3-gbdt.html",     num: "L3·1", title: "GBDT 与特征工程",       level: "L3 机器学习" },
    { file: "l3-labels.html",   num: "L3·2", title: "标签设计与时序防泄漏",  level: "L3 机器学习" },
    { file: "l3-eval.html",     num: "L3·3", title: "模型评估与可解释性",    level: "L3 机器学习" },
    { file: "l4-llm.html",      num: "L4·1", title: "LLM 在量化中的角色",    level: "L4 AI 前沿" },
    { file: "l4-cases.html",    num: "L4·2", title: "7 个开源项目案例剖析",  level: "L4 AI 前沿" }
  ];
  var KEY = "ap_kb_done_v1";

  function curFile() {
    var p = location.pathname.split("/").pop();
    return p && p.length ? p : "index.html";
  }
  function getDone() {
    try { return JSON.parse(localStorage.getItem(KEY) || "{}"); }
    catch (e) { return {}; }
  }
  function setDone(d) {
    try { localStorage.setItem(KEY, JSON.stringify(d)); } catch (e) {}
  }
  function markDone(file) {
    var d = getDone(); d[file] = 1; setDone(d);
    renderSidebar(); renderCards();
  }
  function toggleDone(file) {
    var d = getDone();
    if (d[file]) { delete d[file]; } else { d[file] = 1; }
    setDone(d);
    renderSidebar(); renderCards(); renderPager();
  }
  function doneCount() {
    var d = getDone(), n = 0;
    for (var i = 1; i < AP_CHAPTERS.length; i++) if (d[AP_CHAPTERS[i].file]) n++;
    return n;
  }

  /* ---------- 侧边栏 ---------- */
  function renderSidebar() {
    var el = document.getElementById("sidebar");
    if (!el) return;
    var d = getDone(), cur = curFile();
    var total = AP_CHAPTERS.length - 1;
    var pct = Math.round(doneCount() / total * 100);
    var h = '<a class="brand" href="index.html"><b>AlphaPulse</b> 知识库</a>' +
      '<div class="brand-sub">量化与AI · 从盘感到系统</div>' +
      '<div class="progress-wrap"><div class="progress-label">学习进度 ' + doneCount() + '/' + total + '（' + pct + '%）</div>' +
      '<div class="progress-bar"><div style="width:' + pct + '%"></div></div></div>';
    var lastLevel = null;
    for (var i = 0; i < AP_CHAPTERS.length; i++) {
      var c = AP_CHAPTERS[i];
      if (c.level !== lastLevel && c.level) {
        h += '<div class="nav-level">' + c.level + '</div>';
        lastLevel = c.level;
      }
      var tick = d[c.file] ? '<span class="tick">✔</span>' : '<span class="tick unread">●</span>';
      var cls = "nav-item" + (c.file === cur ? " active" : "");
      h += '<a class="' + cls + '" href="' + c.file + '">' + tick + '<span>' + c.title + '</span></a>';
    }
    el.innerHTML = h;
  }

  /* ---------- 首页章节卡状态 ---------- */
  function renderCards() {
    var d = getDone();
    var cards = document.querySelectorAll(".ch-card[data-file]");
    for (var i = 0; i < cards.length; i++) {
      var f = cards[i].getAttribute("data-file");
      var st = cards[i].querySelector(".state");
      if (!st) continue;
      if (d[f]) { st.textContent = "✔ 已完成"; st.className = "state done"; }
      else { st.textContent = "○ 未学习"; st.className = "state todo"; }
    }
  }

  /* ---------- 翻页 ---------- */
  function renderPager() {
    var el = document.getElementById("pager");
    if (!el) return;
    var cur = curFile(), idx = -1;
    for (var i = 0; i < AP_CHAPTERS.length; i++) if (AP_CHAPTERS[i].file === cur) idx = i;
    if (idx < 0) return;
    var h = "";
    if (idx > 0) {
      var p = AP_CHAPTERS[idx - 1];
      h += '<a href="' + p.file + '">← ' + p.title + '<small>上一章 ' + p.num + '</small></a>';
    } else { h += "<span></span>"; }
    if (idx > 0) {
      var done = getDone()[cur];
      h += '<a href="javascript:void(0)" id="mark-done-btn">' + (done ? "✔ 已读（点击取消）" : "○ 标记本章已读") + "</a>";
    }
    if (idx < AP_CHAPTERS.length - 1) {
      var n = AP_CHAPTERS[idx + 1];
      h += '<a href="' + n.file + '">' + n.title + ' →<small>下一章 ' + n.num + '</small></a>';
    } else { h += "<span></span>"; }
    el.innerHTML = h;
    var btn = document.getElementById("mark-done-btn");
    if (btn) btn.addEventListener("click", function () { toggleDone(cur); });
  }

  /* ---------- 测验 ---------- */
  window.apGradeQuiz = function (btn) {
    var wrap = btn.closest(".quiz-wrap");
    if (!wrap) return;
    var qs = wrap.querySelectorAll(".quiz-q");
    var right = 0, answered = 0;
    for (var i = 0; i < qs.length; i++) {
      var q = qs[i];
      var ans = q.getAttribute("data-answer");
      var chosen = q.querySelector("input:checked");
      q.classList.remove("right", "wrong");
      q.classList.add("graded");
      if (chosen) {
        answered++;
        if (chosen.value === ans) { right++; q.classList.add("right"); }
        else { q.classList.add("wrong"); }
      } else {
        q.classList.add("wrong");
      }
    }
    var score = wrap.querySelector(".quiz-score");
    if (score) {
      var msg = "得分：" + right + " / " + qs.length;
      if (answered < qs.length) msg += "（还有 " + (qs.length - answered) + " 题未作答）";
      else if (right === qs.length) msg += " — 全对，本章已自动标记完成 ✔";
      else msg += " — 看看红框题目下方的解析，再战一次";
      score.textContent = msg;
      score.style.color = right === qs.length ? "var(--down)" : "var(--up)";
    }
    if (right === qs.length && answered === qs.length) markDone(curFile());
    renderPager();
  };

  /* ---------- 术语 tooltip ---------- */
  var tip = null;
  function ensureTip() {
    if (tip) return tip;
    tip = document.createElement("div");
    tip.id = "ap-tip";
    tip.style.display = "none";
    document.body.appendChild(tip);
    return tip;
  }
  function showTip(target) {
    var name = target.getAttribute("data-t") || target.textContent.trim();
    var g = (typeof AP_GLOSSARY !== "undefined") ? AP_GLOSSARY : {};
    var def = g[name];
    if (!def) return;
    var t = ensureTip();
    t.innerHTML = '<div class="tip-name">' + name + "</div>" + def;
    t.style.display = "block";
    var r = target.getBoundingClientRect();
    var x = r.left + window.scrollX;
    var y = r.bottom + window.scrollY + 8;
    t.style.left = "0px"; t.style.top = "0px"; // 先复位再量宽
    var w = t.offsetWidth;
    var maxX = window.scrollX + document.documentElement.clientWidth - w - 12;
    if (x > maxX) x = Math.max(window.scrollX + 8, maxX);
    t.style.left = x + "px";
    t.style.top = y + "px";
  }
  function hideTip() { if (tip) tip.style.display = "none"; }

  document.addEventListener("mouseover", function (e) {
    var t = e.target.closest ? e.target.closest(".term") : null;
    if (t) showTip(t);
  });
  document.addEventListener("mouseout", function (e) {
    var t = e.target.closest ? e.target.closest(".term") : null;
    if (t) hideTip();
  });
  // 移动端：点按术语切换
  document.addEventListener("click", function (e) {
    var t = e.target.closest ? e.target.closest(".term") : null;
    if (t) {
      if (tip && tip.style.display === "block") hideTip(); else showTip(t);
    } else if (tip && tip.style.display === "block" && !(e.target.closest && e.target.closest("#ap-tip"))) {
      hideTip();
    }
  });

  /* ---------- 滑杆通用辅助：自动把 input[data-out] 的值显示到对应元素 ---------- */
  window.apBindSliders = function (scope, onChange) {
    var root = typeof scope === "string" ? document.getElementById(scope) : scope;
    if (!root) return;
    var inputs = root.querySelectorAll("input[type=range]");
    function update() {
      for (var i = 0; i < inputs.length; i++) {
        var inp = inputs[i];
        var outId = inp.getAttribute("data-out");
        if (outId) {
          var out = document.getElementById(outId);
          if (out) {
            var unit = inp.getAttribute("data-unit") || "";
            out.textContent = inp.value + unit;
          }
        }
      }
      if (onChange) onChange();
    }
    for (var i = 0; i < inputs.length; i++) inputs[i].addEventListener("input", update);
    update();
  };

  /* ---------- 启动 ---------- */
  document.addEventListener("DOMContentLoaded", function () {
    renderSidebar();
    renderPager();
    renderCards();
  });
})();
