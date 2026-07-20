// ==UserScript==
// @name         员工通知网页自动登录助手
// @namespace    https://github.com/automation/auto_login_notice
// @version      0.1.0
// @description  工作日 9:00 自动打开公司内网员工通知网页并完成登录（仅跳过周末，当天只触发一次，错过不补）
// @author       automation
// @match        *://*/*
// @grant        GM_openInTab
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_deleteValue
// @grant        GM_registerMenuCommand
// @run-at       document-idle
// @noframes
// ==/UserScript==

(function () {
    'use strict';

    // ================================================================
    // 配置区（安装前按需修改）
    // ================================================================
    const CONFIG = {
        targetUrl:   '网址',
        triggerTime: '09:00',          // 默认触发时间，可通过菜单覆盖
        username:    'YOUR_USERNAME',  // ← 安装前填入你的用户名
        password:    'YOUR_PASSWORD',  // ← 安装前填入你的密码
    };

    // ================================================================
    // 工具函数
    // ================================================================

    // 获取今天的日期字符串（本地时间，格式 YYYY-MM-DD）
    function getTodayString() {
        const d = new Date();
        const y = d.getFullYear();
        const m = String(d.getMonth() + 1).padStart(2, '0');
        const day = String(d.getDate()).padStart(2, '0');
        return `${y}-${m}-${day}`;
    }

    // 判断今天是否为周末（周六=6, 周日=0）
    function isWeekend() {
        const day = new Date().getDay();
        return day === 0 || day === 6;
    }

    // 获取触发时间（优先读 GM 存储，回落到 CONFIG 默认值）
    function getTriggerTime() {
        return GM_getValue('triggerTime', CONFIG.triggerTime);
    }

    // 获取今天触发时间点的时间戳（毫秒）
    function getTodayTriggerTs() {
        const parts = getTriggerTime().split(':');
        const hh = parseInt(parts[0], 10);
        const mm = parseInt(parts[1], 10);
        const d = new Date();
        d.setHours(hh, mm, 0, 0);
        return d.getTime();
    }

    // 判断当前页面是否为目标内网页
    function isTargetPage() {
        return location.hostname === '网址' && location.port === '端口';
    }

    // ================================================================
    // 触发调度器（在所有匹配的 http(s) 页面上运行）
    // ================================================================

    // 执行触发动作：标记今日已触发 + 递增 epoch + 刷新/新开目标页
    function doTrigger() {
        const today = getTodayString();
        GM_setValue('lastTriggerDate', today);

        // 递增 triggerEpoch，用于通知已存在的目标标签自刷新
        const newEpoch = (GM_getValue('triggerEpoch', 0) || 0) + 1;
        GM_setValue('triggerEpoch', newEpoch);

        if (isTargetPage()) {
            // 当前就在目标页 —— 直接刷新自身
            console.log('[自动登录] 触发：刷新当前目标页');
            location.reload();
        } else {
            // 当前在别的页面 —— 等 3 秒看是否有目标标签认领
            // 若 3 秒内无人认领（说明没有已打开的目标标签），则新开一个
            setTimeout(function () {
                if (GM_getValue('claimedEpoch', 0) === newEpoch) {
                    console.log('[自动登录] 已有目标标签认领触发，不新开标签');
                } else {
                    console.log('[自动登录] 3 秒内无目标标签认领，新开目标页');
                    GM_openInTab(CONFIG.targetUrl, { active: true });
                }
            }, 3000);
        }
    }

    // 定时检查是否该触发（每 5 秒轮询一次）
    function checkTrigger() {
        // 今天已触发过 —— 跳过
        if (GM_getValue('lastTriggerDate', '') === getTodayString()) return;
        // 周末 —— 跳过
        if (isWeekend()) return;
        // 还没到触发时间 —— 跳过
        if (Date.now() < getTodayTriggerTs()) return;
        // 满足条件，执行触发
        doTrigger();
    }

    // 启动触发调度器
    setInterval(checkTrigger, 5000);

    // ================================================================
    // 目标页登录逻辑（仅在 网址 上运行）
    // ================================================================
    if (isTargetPage()) {

        // 记录本页加载时的 epoch 和触发日期（用于检测后续变化）
        const loadedEpoch = GM_getValue('triggerEpoch', 0) || 0;
        const loadedTriggerDate = GM_getValue('lastTriggerDate', '');

        // 填写登录表单并点击登录按钮
        function fillLogin() {
            const loginScreen = document.getElementById('loginScreen');
            if (!loginScreen) return false;
            // 若登录界面已被隐藏，说明已登录（可能 app.js 自动恢复了会话）
            if (loginScreen.classList.contains('hidden')) {
                console.log('[自动登录] 检测到已登录，跳过填表');
                return true;
            }
            const userInput = document.getElementById('loginUsername');
            const passInput = document.getElementById('loginPassword');
            const loginBtn = document.querySelector('#loginScreen .login-box button');
            if (!userInput || !passInput || !loginBtn) return false;

            // 填入用户名密码
            userInput.value = CONFIG.username;
            passInput.value = CONFIG.password;
            // 派发事件以触发页面框架的事件监听
            userInput.dispatchEvent(new Event('input', { bubbles: true }));
            passInput.dispatchEvent(new Event('input', { bubbles: true }));
            userInput.dispatchEvent(new Event('change', { bubbles: true }));
            passInput.dispatchEvent(new Event('change', { bubbles: true }));

            // 点击登录按钮
            loginBtn.click();
            console.log('[自动登录] 已填入凭据并点击登录');
            return true;
        }

        // 带重试的登录尝试（DOM 可能尚未就绪）
        function attemptLogin(retries) {
            retries = retries || 0;
            if (retries >= 10) {
                console.warn('[自动登录] 登录表单未出现，放弃');
                return;
            }
            if (!fillLogin()) {
                setTimeout(function () { attemptLogin(retries + 1); }, 500);
            }
        }

        // 若本页加载时今天已触发，等 3 秒让 app.js 稳定后执行登录
        if (loadedTriggerDate === getTodayString()) {
            setTimeout(function () { attemptLogin(0); }, 3000);
        }

        // 轮询检测 triggerEpoch 变化（其他标签触发时本标签应自刷新）
        setInterval(function () {
            const currentEpoch = GM_getValue('triggerEpoch', 0) || 0;
            if (GM_getValue('lastTriggerDate', '') === getTodayString()
                && currentEpoch !== loadedEpoch) {
                // 认领本次触发，防止其他标签新开重复标签
                GM_setValue('claimedEpoch', currentEpoch);
                console.log('[自动登录] 检测到新触发，刷新本页');
                location.reload();
            }
        }, 3000);
    }

    // ================================================================
    // 油猴菜单命令
    // ================================================================

    // 设置触发时间
    GM_registerMenuCommand('⏰ 设置触发时间', function () {
        const current = getTriggerTime();
        const input = prompt('请输入触发时间（格式 HH:MM，如 09:00）', current);
        if (input === null) return;
        const trimmed = input.trim();
        // 简单格式校验
        if (!/^\d{1,2}:\d{2}$/.test(trimmed)) {
            alert('格式不正确，请使用 HH:MM 格式（如 09:00）');
            return;
        }
        GM_setValue('triggerTime', trimmed);
        // 清除今日触发状态，让新时间立即生效
        GM_deleteValue('lastTriggerDate');
        alert('触发时间已设为 ' + trimmed + '，今日触发状态已重置');
    });

    // 立即测试触发（绕过周末和时间检查）
    GM_registerMenuCommand('🧪 立即测试触发', function () {
        if (!confirm('将立即触发一次（标记今日已触发 + 打开/刷新目标页）。\n\n这会阻塞今天到达真实触发时间时的自动触发。\n测试完成后可用「重置今日触发状态」恢复。\n\n继续？')) return;
        doTrigger();
    });

    // 重置今日触发状态
    GM_registerMenuCommand('🔄 重置今日触发状态', function () {
        GM_deleteValue('lastTriggerDate');
        alert('今日触发状态已重置。下次轮询时若满足条件会重新触发。');
    });

})();
