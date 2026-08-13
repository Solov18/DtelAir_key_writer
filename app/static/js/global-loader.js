(() => {
    const root = document.getElementById("globalLoader");
    if (!root) return;

    const overlayDelay = 260;
    const requests = new Map();
    let nextRequestId = 0;
    let overlayTimer = 0;
    let finishTimer = 0;
    let suppressNextNavigation = false;

    const hasBlockingRequest = () => [...requests.values()].some((item) => item.overlay);

    function updateOverlay() {
        if (!hasBlockingRequest()) {
            window.clearTimeout(overlayTimer);
            overlayTimer = 0;
            root.classList.remove("is-overlay-visible");
            document.body.classList.remove("global-loader-blocking");
            return;
        }

        if (overlayTimer || root.classList.contains("is-overlay-visible")) return;
        overlayTimer = window.setTimeout(() => {
            overlayTimer = 0;
            if (!hasBlockingRequest()) return;
            root.classList.add("is-overlay-visible");
            document.body.classList.add("global-loader-blocking");
        }, overlayDelay);
    }

    function show(options = {}) {
        const requestId = ++nextRequestId;
        const overlay = Boolean(options.overlay || options.blocking);
        const request = {overlay, safetyTimer: 0};
        requests.set(requestId, request);
        // A lost navigation or a broken third-party handler must never leave
        // the whole application blocked forever. Fetch/XHR still release the
        // exact token in their completion path; this is only a final guard.
        const maxDuration = Number(options.maxDuration || 120000);
        if (Number.isFinite(maxDuration) && maxDuration > 0) {
            request.safetyTimer = window.setTimeout(() => hide(requestId), maxDuration);
        }
        window.clearTimeout(finishTimer);
        root.classList.remove("is-finishing");
        root.classList.add("is-active");
        root.setAttribute("aria-hidden", "false");
        document.documentElement.setAttribute("aria-busy", "true");
        if (overlay) updateOverlay();
        return requestId;
    }

    function hide(requestId) {
        const targetId = requestId == null
            ? requests.keys().next().value
            : requestId;
        const request = targetId == null ? null : requests.get(targetId);
        if (request?.safetyTimer) window.clearTimeout(request.safetyTimer);
        if (targetId != null) requests.delete(targetId);
        console.debug("global_loader.hide", {requestId: targetId, remaining: requests.size});

        if (requests.size) {
            updateOverlay();
            return;
        }

        window.clearTimeout(overlayTimer);
        overlayTimer = 0;
        root.classList.remove("is-overlay-visible");
        document.body.classList.remove("global-loader-blocking");
        document.documentElement.removeAttribute("aria-busy");
        root.classList.add("is-finishing");
        finishTimer = window.setTimeout(() => {
            if (requests.size) return;
            root.classList.remove("is-active", "is-finishing");
            root.setAttribute("aria-hidden", "true");
        }, 240);
    }

    function reset() {
        requests.forEach((request) => {
            if (request.safetyTimer) window.clearTimeout(request.safetyTimer);
        });
        requests.clear();
        window.clearTimeout(overlayTimer);
        window.clearTimeout(finishTimer);
        overlayTimer = 0;
        finishTimer = 0;
        root.classList.remove("is-active", "is-finishing", "is-overlay-visible");
        root.setAttribute("aria-hidden", "true");
        document.body.classList.remove("global-loader-blocking");
        document.documentElement.removeAttribute("aria-busy");
        console.debug("global_loader.reset", {reason: "page-ready"});
    }

    function resourceUrl(resource) {
        if (resource instanceof Request) return resource.url;
        return String(resource || "");
    }

    function shouldBlockRequest(resource, options = {}) {
        const loaderOption = options.globalLoader;
        if (loaderOption && typeof loaderOption === "object") {
            return Boolean(loaderOption.overlay || loaderOption.blocking);
        }
        if (loaderOption === "overlay" || loaderOption === "blocking") return true;

        const method = String(options.method || (resource instanceof Request ? resource.method : "GET")).toUpperCase();
        if (["GET", "HEAD", "OPTIONS"].includes(method)) return false;
        const pathname = (() => {
            try { return new URL(resourceUrl(resource), window.location.href).pathname.toLowerCase(); }
            catch (_) { return ""; }
        })();
        return /(?:\/import|\/delete|\/archive|\/reboot|\/bulk|\/remove|\/unlink)/.test(pathname);
    }

    window.showGlobalLoader = show;
    window.hideGlobalLoader = hide;
    window.suppressGlobalLoaderForNextNavigation = () => {
        suppressNextNavigation = true;
        reset();
    };

    async function runWithLoader(task, options = {}) {
        const requestId = show(options);
        try {
            return await task();
        } finally {
            hide(requestId);
        }
    }

    window.runWithGlobalLoader = runWithLoader;

    async function submitHtmlForm(form, {submitter = null} = {}) {
        if (!(form instanceof HTMLFormElement)) {
            throw new TypeError("Ожидалась HTML-форма");
        }
        const action = submitter?.formAction || form.action || window.location.href;
        const method = String(submitter?.formMethod || form.method || "POST").toUpperCase();
        console.info("key_write.request.start", {action, method});
        return runWithLoader(async () => {
            const controller = new AbortController();
            const requestTimeout = window.setTimeout(() => controller.abort(), 45000);
            let response;
            try {
                response = await window.fetch(action, {
                    method,
                    body: new FormData(form),
                    headers: {
                        "Accept": "application/json",
                        "X-Requested-With": "KeyWriterAsync",
                    },
                    signal: controller.signal,
                    globalLoader: false,
                });
            } catch (error) {
                if (error?.name === "AbortError") {
                    throw new Error("Сервер не завершил запись за 45 секунд. Проверьте доступность CRM и повторите операцию.");
                }
                throw error;
            } finally {
                window.clearTimeout(requestTimeout);
            }
            let payload;
            try {
                payload = await response.json();
            } catch (error) {
                throw new Error("Сервер вернул некорректный ответ. Повторите операцию.", {cause: error});
            }
            if (!response.ok || !payload?.ok || typeof payload.html !== "string") {
                throw new Error(payload?.error || `Ошибка сервера: HTTP ${response.status}`);
            }
            console.info("key_write.request.finish", {status: response.status});
            return payload;
        }, {overlay: true, maxDuration: 50000});
    }

    function renderHtmlResponse(payload) {
        if (!payload?.html || !/<html[\s>]/i.test(payload.html)) {
            throw new Error("Экран результата не получен от сервера.");
        }
        if (payload.url) window.history.pushState(null, "", payload.url);
        document.open("text/html", "replace");
        document.write(payload.html);
        document.close();
    }

    window.submitHtmlFormWithLoader = submitHtmlForm;
    window.renderHtmlResponse = renderHtmlResponse;

    const wrappedFetch = window.fetch.bind(window);
    window.fetch = (resource, options = {}) => {
        if (options.globalLoader === false) return wrappedFetch(resource, options);
        const requestOptions = {...options};
        delete requestOptions.globalLoader;
        return runWithLoader(
            () => wrappedFetch(resource, requestOptions),
            {overlay: shouldBlockRequest(resource, options)}
        );
    };

    const NativeXMLHttpRequest = window.XMLHttpRequest;
    if (NativeXMLHttpRequest) {
        const nativeOpen = NativeXMLHttpRequest.prototype.open;
        const nativeSend = NativeXMLHttpRequest.prototype.send;

        NativeXMLHttpRequest.prototype.open = function (method, url, ...rest) {
            this.__globalLoaderMethod = method;
            this.__globalLoaderUrl = url;
            return nativeOpen.call(this, method, url, ...rest);
        };

        NativeXMLHttpRequest.prototype.send = function (...args) {
            if (this.__globalLoaderDisabled) return nativeSend.apply(this, args);
            const requestId = show({
                overlay: shouldBlockRequest(this.__globalLoaderUrl, {
                    method: this.__globalLoaderMethod,
                    globalLoader: this.__globalLoaderMode,
                }),
            });
            let requestFinished = false;
            const finishRequest = () => {
                if (requestFinished) return;
                requestFinished = true;
                hide(requestId);
            };
            this.addEventListener("loadend", finishRequest, {once: true});
            this.addEventListener("error", finishRequest, {once: true});
            this.addEventListener("abort", finishRequest, {once: true});
            this.addEventListener("timeout", finishRequest, {once: true});
            try {
                return nativeSend.apply(this, args);
            } catch (error) {
                finishRequest();
                throw error;
            }
        };
    }

    function isDownloadLink(anchor) {
        if (anchor.hasAttribute("download")) return true;
        try {
            return /\/(?:export|download)(?:\/|$)/i.test(new URL(anchor.href, window.location.href).pathname);
        } catch (_) {
            return false;
        }
    }

    const delegatedNavigationSelector = "[data-href], [data-select-url], [data-panel-url]";
    const nestedInteractiveSelector = [
        "a",
        "button",
        "input",
        "select",
        "textarea",
        "label",
        "form",
        "summary",
        "[role='button']",
        "[contenteditable='true']",
    ].join(", ");

    function isNestedInteractiveClick(event, navigationTarget) {
        const interactive = event.target.closest?.(nestedInteractiveSelector);
        return Boolean(
            interactive
            && interactive !== navigationTarget
            && navigationTarget.contains(interactive)
        );
    }

    function showNavigationLoader() {
        // If another script cancels or handles a delegated navigation without
        // unloading the page, the UI must never remain blocked indefinitely.
        return show({overlay: true, maxDuration: 30000});
    }

    document.addEventListener("click", (event) => {
        if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        const anchor = event.target.closest?.("a[href]");
        if (anchor) {
            if (anchor.dataset.noLoader != null || anchor.target && anchor.target !== "_self" || isDownloadLink(anchor)) return;
            let destination;
            try { destination = new URL(anchor.href, window.location.href); }
            catch (_) { return; }
            if (destination.origin !== window.location.origin || !["http:", "https:"].includes(destination.protocol)) return;
            if (destination.pathname === window.location.pathname && destination.search === window.location.search && destination.hash) return;
            queueMicrotask(() => {
                if (!event.defaultPrevented) showNavigationLoader();
            });
            return;
        }

        const navigationTarget = event.target.closest?.(delegatedNavigationSelector);
        if (navigationTarget) {
            // Rows and cards often contain edit/delete/reveal controls.  Their
            // click opens a modal or performs an inline action, not navigation.
            if (isNestedInteractiveClick(event, navigationTarget)) return;
            queueMicrotask(() => {
                if (!event.defaultPrevented) showNavigationLoader();
            });
        }
    }, true);

    document.addEventListener("submit", (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement) || form.dataset.noLoader != null) return;
        if (form.target && form.target !== "_self" || form.method.toLowerCase() === "dialog") return;
        const method = String(event.submitter?.formMethod || form.method || "GET").toUpperCase();
        let action;
        try { action = new URL(event.submitter?.formAction || form.action || window.location.href, window.location.href); }
        catch (_) { return; }
        if (action.origin !== window.location.origin || /\/(?:export|download)(?:\/|$)/i.test(action.pathname)) return;
        queueMicrotask(() => {
            if (!event.defaultPrevented) show({overlay: method !== "GET"});
        });
    }, true);

    const nativeFormSubmit = HTMLFormElement.prototype.submit;
    HTMLFormElement.prototype.submit = function () {
        if (this.dataset.noLoader == null && (!this.target || this.target === "_self")) {
            const method = String(this.method || "GET").toUpperCase();
            let action;
            try { action = new URL(this.action || window.location.href, window.location.href); }
            catch (_) { action = null; }
            if (action?.origin === window.location.origin && !/\/(?:export|download)(?:\/|$)/i.test(action.pathname)) {
                show({overlay: method !== "GET"});
            }
        }
        return nativeFormSubmit.call(this);
    };

    window.addEventListener("pageshow", reset);
    window.addEventListener("beforeunload", () => {
        if (suppressNextNavigation) return;
        if (!requests.size) show({overlay: true});
    });
})();
