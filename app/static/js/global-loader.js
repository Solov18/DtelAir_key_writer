(() => {
    const root = document.getElementById("globalLoader");
    if (!root) return;

    const overlayDelay = 260;
    const requests = new Map();
    let nextRequestId = 0;
    let overlayTimer = 0;
    let finishTimer = 0;
    let suppressNextNavigation = false;
    let suppressNavigationTimer = 0;
    let navigationRequestId = null;
    let unloadFallbackTimer = 0;

    const hasBlockingRequest = () => [...requests.values()].some((item) => item.overlay);
    const hasCollapsibleRequest = () => [...requests.values()].some(
        (item) => item.overlay && item.collapsible
    );

    function updateOverlay() {
        if (!hasBlockingRequest()) {
            window.clearTimeout(overlayTimer);
            overlayTimer = 0;
            root.classList.remove("is-overlay-visible");
            document.body.classList.remove("global-loader-blocking");
            root.classList.remove("is-collapsible");
            return;
        }

        root.classList.toggle("is-collapsible", hasCollapsibleRequest());

        if (overlayTimer || root.classList.contains("is-overlay-visible")) return;
        overlayTimer = window.setTimeout(() => {
            overlayTimer = 0;
            if (!hasBlockingRequest()) return;
            root.classList.add("is-overlay-visible");
            document.body.classList.add("global-loader-blocking");
        }, overlayDelay);
    }

    function begin(options = {}) {
        const requestId = ++nextRequestId;
        const overlay = Boolean(options.overlay || options.blocking);
        const request = {
            overlay,
            collapsible: Boolean(options.collapsible),
            safetyTimer: 0,
        };
        requests.set(requestId, request);
        // A lost navigation or a broken third-party handler must never leave
        // the whole application blocked forever. Fetch/XHR still release the
        // exact token in their completion path; this is only a final guard.
        const maxDuration = Number(options.maxDuration || 120000);
        if (Number.isFinite(maxDuration) && maxDuration > 0) {
            request.safetyTimer = window.setTimeout(() => end(requestId), maxDuration);
        }
        window.clearTimeout(finishTimer);
        root.classList.remove("is-finishing");
        root.classList.add("is-active");
        root.setAttribute("aria-hidden", "false");
        document.documentElement.setAttribute("aria-busy", "true");
        if (overlay) updateOverlay();
        return requestId;
    }

    function end(requestId) {
        if (requestId == null || !requests.has(requestId)) return false;
        const request = requests.get(requestId);
        if (request?.safetyTimer) window.clearTimeout(request.safetyTimer);
        requests.delete(requestId);
        if (navigationRequestId === requestId) navigationRequestId = null;
        if (requests.size) {
            updateOverlay();
            return true;
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
        return true;
    }

    function reset() {
        requests.forEach((request) => {
            if (request.safetyTimer) window.clearTimeout(request.safetyTimer);
        });
        requests.clear();
        window.clearTimeout(overlayTimer);
        window.clearTimeout(finishTimer);
        window.clearTimeout(unloadFallbackTimer);
        overlayTimer = 0;
        finishTimer = 0;
        unloadFallbackTimer = 0;
        navigationRequestId = null;
        root.classList.remove("is-active", "is-finishing", "is-overlay-visible", "is-collapsible");
        root.setAttribute("aria-hidden", "true");
        document.body.classList.remove("global-loader-blocking");
        document.documentElement.removeAttribute("aria-busy");
    }

    function suppressNavigationLoader() {
        suppressNextNavigation = true;
        window.clearTimeout(suppressNavigationTimer);
        reset();
        // Downloads can fire beforeunload without unloading the document.
        // Release the suppression shortly afterwards so later navigation keeps
        // the normal loader behaviour.
        suppressNavigationTimer = window.setTimeout(() => {
            suppressNextNavigation = false;
            suppressNavigationTimer = 0;
        }, 3000);
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

    async function runWithLoader(task, options = {}) {
        const requestId = begin(options);
        try {
            return await task();
        } finally {
            end(requestId);
        }
    }

    function beginNavigation(options = {}) {
        if (navigationRequestId != null) end(navigationRequestId);
        navigationRequestId = begin({
            overlay: true,
            maxDuration: 30000,
            ...options,
        });
        return navigationRequestId;
    }

    function navigate(url, {replace = false} = {}) {
        beginNavigation();
        if (replace) window.location.replace(url);
        else window.location.assign(url);
    }

    const GlobalLoader = {
        begin,
        end,
        reset,
        run: runWithLoader,
        navigate,
        beginNavigation,
        get activeCount() { return requests.size; },
    };

    window.GlobalLoader = GlobalLoader;

    function formAction(form, submitter = null) {
        // `HTMLButtonElement.formAction` resolves to the current document URL
        // even when the button has no `formaction` attribute.  Reading that
        // property unconditionally used to turn e.g. `/keys/import` into
        // `POST /keys` (HTTP 405).  A submit button may override the form only
        // when the override is explicitly present in the markup.
        if (submitter?.hasAttribute?.("formaction")) {
            return submitter.formAction;
        }
        return form.action || window.location.href;
    }

    function formMethod(form, submitter = null) {
        if (submitter?.hasAttribute?.("formmethod")) {
            return String(submitter.formMethod || "GET").toUpperCase();
        }
        return String(form.method || "GET").toUpperCase();
    }

    root.querySelector("[data-global-loader-collapse]")?.addEventListener("click", () => {
        requests.forEach((request) => {
            if (request.collapsible) request.overlay = false;
        });
        updateOverlay();
    });

    const wrappedFetch = window.fetch.bind(window);
    window.fetch = (resource, options = {}) => {
        const requestOptions = {...options};
        delete requestOptions.globalLoader;
        if (options.globalLoader === false) return wrappedFetch(resource, requestOptions);
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
            const requestId = begin({
                overlay: shouldBlockRequest(this.__globalLoaderUrl, {
                    method: this.__globalLoaderMethod,
                    globalLoader: this.__globalLoaderMode,
                }),
            });
            let requestFinished = false;
            const finishRequest = () => {
                if (requestFinished) return;
                requestFinished = true;
                end(requestId);
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

    function downloadFilename(response, anchor) {
        const disposition = response.headers.get("Content-Disposition") || "";
        const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
        if (encoded) {
            try { return decodeURIComponent(encoded); }
            catch (_) { /* use the remaining fallbacks */ }
        }
        const quoted = disposition.match(/filename="([^"]+)"/i)?.[1];
        const plain = disposition.match(/filename=([^;\s]+)/i)?.[1];
        if (quoted || plain) return quoted || plain;
        if (anchor.getAttribute("download")) return anchor.getAttribute("download");
        try {
            return new URL(anchor.href, window.location.href).pathname.split("/").pop() || "download";
        } catch (_) {
            return "download";
        }
    }

    async function downloadLink(anchor) {
        return runWithLoader(async () => {
            const controller = new AbortController();
            const requestTimeout = window.setTimeout(() => controller.abort(), 120000);
            let response;
            try {
                response = await wrappedFetch(anchor.href, {
                    credentials: "same-origin",
                    signal: controller.signal,
                    headers: {"X-Requested-With": "KeyWriterDownload"},
                });
            } catch (error) {
                if (error?.name === "AbortError") {
                    throw new Error("Сервер не сформировал файл за 2 минуты. Повторите выгрузку.");
                }
                throw error;
            } finally {
                window.clearTimeout(requestTimeout);
            }
            if (!response.ok) {
                throw new Error(`Не удалось скачать файл: сервер вернул HTTP ${response.status}.`);
            }

            const contentType = (response.headers.get("Content-Type") || "").toLowerCase();
            if (contentType.includes("text/html")) {
                throw new Error("Вместо файла сервер вернул HTML-страницу. Обновите страницу, войдите снова и повторите выгрузку.");
            }

            const blob = await response.blob();
            const objectUrl = URL.createObjectURL(blob);
            const helper = document.createElement("a");
            helper.href = objectUrl;
            helper.download = downloadFilename(response, anchor);
            helper.hidden = true;
            helper.dataset.loaderNativeDownload = "";
            document.body.appendChild(helper);
            try {
                helper.click();
            } finally {
                helper.remove();
                window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
            }
        }, {overlay: false, maxDuration: 125000});
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
        return beginNavigation({overlay: true, maxDuration: 30000});
    }

    document.addEventListener("click", (event) => {
        if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        const anchor = event.target.closest?.("a[href]");
        if (anchor) {
            if (anchor.dataset.loaderNativeDownload != null) return;
            if (isDownloadLink(anchor)) {
                let destination;
                try { destination = new URL(anchor.href, window.location.href); }
                catch (_) { return; }
                if (destination.origin !== window.location.origin) return;
                event.preventDefault();
                void downloadLink(anchor).catch(async (error) => {
                    await window.showAlert?.({
                        title: "Выгрузка не завершена",
                        message: error?.message || "Не удалось скачать файл.",
                        confirmText: "Закрыть",
                        source: anchor,
                    });
                });
                return;
            }
            if (anchor.dataset.noLoader != null) {
                suppressNavigationLoader();
                return;
            }
            if (anchor.target && anchor.target !== "_self") return;
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
        if (!(form instanceof HTMLFormElement)) return;
        if (form.dataset.noLoader != null) {
            suppressNavigationLoader();
            return;
        }
        if (form.target && form.target !== "_self" || form.method.toLowerCase() === "dialog") return;
        const method = formMethod(form, event.submitter);
        let action;
        try { action = new URL(formAction(form, event.submitter), window.location.href); }
        catch (_) { return; }
        if (action.origin !== window.location.origin) return;
        if (/\/(?:export|download)(?:\/|$)/i.test(action.pathname)) {
            // Export links are downloaded through downloadLink().  A native
            // export form must not create an unowned navigation token because
            // the browser may keep the current document alive.
            suppressNavigationLoader();
            return;
        }
        queueMicrotask(() => {
            if (!event.defaultPrevented) {
                const longNavigation = form.dataset.loaderLongNavigation != null;
                beginNavigation({
                    overlay: method !== "GET",
                    collapsible: longNavigation,
                    maxDuration: longNavigation ? 305000 : 120000,
                });
            }
        });
    }, true);

    const nativeFormSubmit = HTMLFormElement.prototype.submit;
    HTMLFormElement.prototype.submit = function () {
        if (this.dataset.noLoader != null) {
            suppressNavigationLoader();
        } else if (!this.target || this.target === "_self") {
            const method = String(this.method || "GET").toUpperCase();
            let action;
            try { action = new URL(this.action || window.location.href, window.location.href); }
            catch (_) { action = null; }
            if (action?.origin === window.location.origin && /\/(?:export|download)(?:\/|$)/i.test(action.pathname)) {
                suppressNavigationLoader();
            } else if (action?.origin === window.location.origin) {
                beginNavigation({overlay: method !== "GET"});
            }
        }
        return nativeFormSubmit.call(this);
    };

    GlobalLoader.submitForm = (form) => {
        if (!(form instanceof HTMLFormElement)) throw new TypeError("Expected an HTML form");
        return HTMLFormElement.prototype.submit.call(form);
    };

    // The old implementation started a fresh, ownerless request inside
    // beforeunload.  When navigation was cancelled or a bfcache page was
    // restored, no completion path existed and the overlay stayed forever.
    // Navigation tokens are now created by the click/submit owner; lifecycle
    // events only clean state that belongs to the document being left/restored.
    window.addEventListener("pageshow", reset);
    window.addEventListener("pagehide", reset);
    window.addEventListener("beforeunload", () => {
        window.clearTimeout(unloadFallbackTimer);
        unloadFallbackTimer = window.setTimeout(() => {
            // If the document is still visible, navigation was cancelled.
            if (document.visibilityState === "visible") reset();
        }, 0);
    });
})();
