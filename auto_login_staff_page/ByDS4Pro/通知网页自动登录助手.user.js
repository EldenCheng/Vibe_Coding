// ==UserScript==
// @name         员工通知网页自动登录
// @namespace    网址
// @version      1.2.0
// @description  工作日 9:00 自动打开员工通知网页并填入凭据登录
// @author       elden.zheng
// @match        *://*/*
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_addValueChangeListener
// @grant        unsafeWindow
// ==/UserScript==

(function() {
    'use strict';

    /* =========================== 配置区 ===========================
       修改以下常量即可调整行为（测试时改 TRIGGER_HOUR/MINUTE 即可）
       ============================================================ */
    const TARGET_URL        = '网址';
    const TRIGGER_HOUR      = 9;         // 触发小时（24 小时制）
    const TRIGGER_MINUTE    = 0;         // 触发分钟
    const USERNAME          = 'elden.zheng';
    const PASSWORD          = 'password';
    const USER_SEL          = '#loginUsername';  // 用户名输入框选择器
    const PASS_SEL          = '#loginPassword';  // 密码输入框选择器
    const LOGIN_BTN_SEL     = '#loginScreen button';  // 登录按钮选择器
    /* ============================================================ */

    // 判断当前页是否目标 URL
    function isTargetPage() {
        return window.location.href.startsWith(TARGET_URL);
    }

    // 计算到下一个工作日 TRIGGER_HOUR:TRIGGER_MINUTE 的毫秒数
    function msToNextWeekdayTrigger() {
        let d = new Date();
        d.setDate(d.getDate() + 1);
        while (d.getDay() === 0 || d.getDay() === 6) {
            d.setDate(d.getDate() + 1);
        }
        d.setHours(TRIGGER_HOUR, TRIGGER_MINUTE, 0, 0);
        return d.getTime() - Date.now();
    }

    // 触发动作：跳转或刷新目标页面
    function doTrigger() {
        const today = new Date().toDateString();

        // 今天已经触发过 → 跳过
        if (GM_getValue('lastTriggerDate') === today) return;

        // 周末不触发
        const day = new Date().getDay();
        if (day === 0 || day === 6) return;

        // 写入当天标记，防重复
        GM_setValue('lastTriggerDate', today);

        // 标记"本次加载需要自动登录"（供 autoLogin 判断）
        GM_setValue('_pendingLogin', today);

        if (isTargetPage()) {
            window.location.reload();
        } else {
            window.location.href = TARGET_URL;
        }
    }

    // 触发时间是否已到（精确到分钟）
    function isTriggerTime() {
        var now = new Date();
        return now.getHours() === TRIGGER_HOUR && now.getMinutes() === TRIGGER_MINUTE;
    }

    // 周期性检查：每 30 秒检查一次触发条件（兜底，防止 setTimeout 因后台节流失效）
    function startPeriodicCheck() {
        setInterval(function() {
            if (isTriggerTime() && !isWeekend()) {
                doTrigger();
            }
        }, 30000);
    }

    // 今天是否周末
    function isWeekend() {
        var d = new Date();
        return d.getDay() === 0 || d.getDay() === 6;
    }

    // 排程：设置一次性定时器到下一个触发时间
    function schedule() {
        var now = new Date();

        var target = new Date(now);
        target.setHours(TRIGGER_HOUR, TRIGGER_MINUTE, 0, 0);
        var ms = target.getTime() - now.getTime();

        if (ms <= 0 || isWeekend()) {
            // 今天已过触发时间，或今天是周末 → 等下个工作日
            setTimeout(doTrigger, msToNextWeekdayTrigger());
        } else {
            // 今天还没到 → 定时等待
            setTimeout(doTrigger, ms);
        }
    }

    // 判断登录屏幕是否可见（未隐藏）
    function isLoginScreenVisible() {
        var el = document.getElementById('loginScreen');
        if (!el) return false;
        if (el.classList.contains('hidden')) return false;
        if (window.getComputedStyle(el).display === 'none') return false;
        return true;
    }

    // 尝试以多种方式触发登录
    function tryLoginNow(user, pass) {
        if (!user || !pass) return false;

        user.value = USERNAME;
        pass.value = PASSWORD;

        // 触发 input 事件让前端框架感知值变化
        user.dispatchEvent(new Event('input', { bubbles: true }));
        pass.dispatchEvent(new Event('input', { bubbles: true }));

        // 方式 1：直接调用页面的 login() 函数
        if (typeof unsafeWindow.login === 'function') {
            unsafeWindow.login();
            return true;
        }

        // 方式 2：点击登录按钮
        var btn = document.querySelector(LOGIN_BTN_SEL);
        if (btn) {
            try { btn.click(); return true; } catch (e) {}
            try {
                btn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                return true;
            } catch (e) {}
        }

        // 方式 3：密码框触 Enter（利用 onkeypress 处理器）
        try {
            pass.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true
            }));
            return true;
        } catch (e) {}

        return false;
    }

    // 判断本次是否应该自动提交登录
    function shouldAutoSubmit() {
        // 是由 doTrigger() 触发加载的 → 是
        if (GM_getValue('_pendingLogin') === new Date().toDateString()) return true;
        // 当前是触发时间 → 是（用户手动刷新也能自动登录）
        if (isTriggerTime()) return true;
        return false;
    }

    // 自动填入用户名密码并触发登录
    function autoLogin() {
        if (!isTargetPage()) return;

        // 每页面的生命周期只管一次
        if (sessionStorage.getItem('_auto_login_done')) return;
        sessionStorage.setItem('_auto_login_done', '1');

        // 登录屏幕不可见 → 说明已登录，跳过
        if (!isLoginScreenVisible()) return;

        // 非触发时间也不属于 trigger 发起的加载 → 跳过
        if (!shouldAutoSubmit()) return;

        // 清除 pending 标记，防止跨标签重复提交
        GM_setValue('_pendingLogin', '');

        var fillAndLogin = function() {
            var user = document.querySelector(USER_SEL);
            var pass = document.querySelector(PASS_SEL);
            return tryLoginNow(user, pass);
        };

        // 如果表单已存在，立即尝试登录
        if (fillAndLogin()) return;

        // 否则等待表单动态加载（最多 15 秒）
        var observer = new MutationObserver(function() {
            if (fillAndLogin()) observer.disconnect();
        });
        observer.observe(document.body, { childList: true, subtree: true });
        setTimeout(function() { observer.disconnect(); }, 15000);
    }

    // 跨标签通信：检测到其他标签页触发时，如果自己在目标页面且登录屏幕可见则刷新
    GM_addValueChangeListener('lastTriggerDate', function(name, oldValue, newValue, remote) {
        if (remote && newValue === new Date().toDateString() && isTargetPage() && isLoginScreenVisible()) {
            window.location.reload();
        }
    });

    // ====== 启动 ======
    autoLogin();
    schedule();
    startPeriodicCheck();

})();
