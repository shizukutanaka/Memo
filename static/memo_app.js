(function () {
    'use strict';

    /**
     * -------------------------------------------------------------------------
     *  THEME MANAGEMENT
     * -------------------------------------------------------------------------
     */
    const themeToggleButton = document.getElementById('theme-toggle');
    const sunIcon = `☀️`;
    const moonIcon = `🌙`;

    const getPreferredTheme = () => {
        const storedTheme = localStorage.getItem('theme');
        if (storedTheme) {
            return storedTheme;
        }
        return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    };

    const setTheme = (theme) => {
        if (theme === 'dark') {
            document.documentElement.setAttribute('data-theme', 'dark');
            if(themeToggleButton) themeToggleButton.innerHTML = sunIcon;
        } else {
            document.documentElement.setAttribute('data-theme', 'light');
            if(themeToggleButton) themeToggleButton.innerHTML = moonIcon;
        }
    };

    const toggleTheme = () => {
        const currentTheme = getPreferredTheme();
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        localStorage.setItem('theme', newTheme);
        setTheme(newTheme);
    };

    // Set initial theme
    setTheme(getPreferredTheme());

    // Add event listener for the toggle button
    if (themeToggleButton) {
        themeToggleButton.addEventListener('click', toggleTheme);
    }

    // Listen for OS theme changes
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
        if (!localStorage.getItem('theme')) {
            setTheme(e.matches ? 'dark' : 'light');
        }
    });

    /**
     * -------------------------------------------------------------------------
     *  APPLICATION STATE & CONSTANTS
     * -------------------------------------------------------------------------
     */
    const state = {
        token: null,
        memos: [],
        filteredMemos: [],
        stats: {},
        socket: null,
        currentPage: 1,
        itemsPerPage: 10,
    };

    const MAX_SEARCH_LENGTH = 256;

    const statusMessageEl = document.getElementById('status-message');
    const loginSection = document.getElementById('login-section');
    const appContainer = document.getElementById('app-container');
    const loginForm = document.getElementById('login-form');
    const memoForm = document.getElementById('memo-form');
    const memoList = document.getElementById('memo-list');
    const paginationContainer = document.getElementById('pagination-container');
    const statsContainer = document.getElementById('stats');
    const searchForm = document.getElementById('search-form');
    const searchInput = document.getElementById('search-input');
    const searchType = document.getElementById('search-type');
    const statusFilter = document.getElementById('status-filter');
    const priorityFilter = document.getElementById('priority-filter');
    const categoryFilter = document.getElementById('category-filter');
    const tagsFilter = document.getElementById('tags-filter');
    const createdFromInput = document.getElementById('created-from');
    const createdToInput = document.getElementById('created-to');
    const clearSearchButton = document.getElementById('clear-search');
    const searchToggle = document.getElementById('search-toggle');
    const searchSection = document.getElementById('search-section');
    const modalContainer = document.getElementById('modal-container');
    const modalTitle = document.getElementById('modal-title');
    const modalBody = document.getElementById('modal-body');
    const modalConfirm = document.getElementById('modal-confirm');
    const modalCancel = document.getElementById('modal-cancel');
    const modalClose = document.getElementById('modal-close');

    const hostsRequireSecureCookies = window.location.protocol === 'https:';

    const showStatus = (message, isError = true) => {
        const iconEl = statusMessageEl.querySelector('.banner-icon');
        const contentEl = statusMessageEl.querySelector('.banner-content');

        if (!message) {
            statusMessageEl.style.display = 'none';
            if(contentEl) contentEl.textContent = '';
            if(iconEl) iconEl.innerHTML = '';
            return;
        }

        if(contentEl) contentEl.textContent = message;
        statusMessageEl.classList.toggle('success', !isError);
        statusMessageEl.classList.toggle('error', isError);
        
        if(iconEl) {
            // Atlassian-style icons (using simple emojis as placeholders)
            iconEl.innerHTML = isError ? '⚠️' : '✅';
        }

        statusMessageEl.style.display = 'flex';
    };

    const resetSession = () => {
        state.token = null;
        state.memos = [];
        state.filteredMemos = [];
        state.stats = {};
        if (state.socket) {
            state.socket.disconnect();
            state.socket = null;
        }
        sessionStorage.removeItem('memo_web_token');
        if (appContainer) appContainer.hidden = true;
        loginSection.parentElement.hidden = false;
    };

    const attachAuthHeader = (init = {}) => {
        if (!state.token) {
            throw new Error('Missing session token');
        }
        const headers = new Headers(init.headers || {});
        headers.set('Authorization', `Bearer ${state.token}`);
        return { ...init, headers };
    };

    const authenticatedFetch = async (input, init) => {
        try {
            const response = await fetch(input, attachAuthHeader(init));
            if (response.status === 401) {
                showStatus('Session expired. Please sign in again.');
                resetSession();
                return null;
            }
            if (response.status === 429) {
                try {
                    const clone = response.clone();
                    const payload = await clone.json();
                    showStatus(payload.message || 'Request rate exceeded. Please try again shortly.');
                } catch (error) {
                    showStatus('Too many requests. Please try again later.');
                }
            }
            return response;
        } catch (error) {
            showStatus('Request failed. Check connectivity and credentials.');
            console.error(error);
            return null;
        }
    };

    const renderStats = () => {
        statsContainer.innerHTML = '';
        if (!state.stats || !Object.keys(state.stats).length) {
            const empty = document.createElement('p');
            empty.textContent = 'No statistics available.';
            statsContainer.appendChild(empty);
            return;
        }

        const { total = 0, by_status: byStatus = {}, by_type: byType = {} } = state.stats;
        const stats = [
            { label: 'Total', value: total },
            { label: 'Active', value: byStatus.active || 0 },
            { label: 'Completed', value: byStatus.completed || 0 },
            { label: 'Archived', value: byStatus.archived || 0 },
            { label: 'Tasks', value: byType.task || 0 },
            { label: 'Ideas', value: byType.idea || 0 },
        ];

        stats.forEach(({ label, value }) => {
            const card = document.createElement('div');
            card.className = 'stat-card';

            const valueEl = document.createElement('div');
            valueEl.className = 'stat-value';
            valueEl.textContent = value;

            const labelEl = document.createElement('div');
            labelEl.textContent = label;

            card.appendChild(valueEl);
            card.appendChild(labelEl);
            statsContainer.appendChild(card);
        });
    };

    const toLocalTime = (isoString) => {
        if (!isoString) {
            return 'n/a';
        }
        try {
            const date = new Date(isoString);
            return date.toLocaleString();
        } catch (error) {
            return isoString;
        }
    };

    const renderMemo = (memo) => {
        const article = document.createElement('article');
        article.className = 'memo-card';
        article.dataset.memoId = memo.id;

        // Create priority lozenge
        const createLozenge = (text, appearance) => {
            const lozenge = document.createElement('span');
            lozenge.className = `lozenge lozenge-${appearance}`;
            lozenge.textContent = text;
            return lozenge;
        };

        const priorityMap = {
            1: { text: 'Critical', appearance: 'danger' },
            2: { text: 'High', appearance: 'warning' },
            3: { text: 'Medium', appearance: 'info' },
            4: { text: 'Low', appearance: 'success' },
            5: { text: 'None', appearance: 'default' }
        };

        const statusMap = {
            'active': { text: 'Active', appearance: 'info' },
            'completed': { text: 'Completed', appearance: 'success' },
            'archived': { text: 'Archived', appearance: 'default' }
        };

        const meta = document.createElement('div');
        meta.className = 'memo-meta';

        const createMetaItem = (label, valueElement) => {
            const item = document.createElement('div');
            item.innerHTML = `<strong>${label}:</strong> `;
            item.appendChild(valueElement);
            return item;
        };

        // Created time
        const createdValue = document.createElement('span');
        createdValue.textContent = toLocalTime(memo.created || memo.timestamp);
        meta.appendChild(createMetaItem('Created', createdValue));

        // Type
        const typeValue = document.createElement('span');
        typeValue.textContent = memo.type;
        meta.appendChild(createMetaItem('Type', typeValue));

        // Priority lozenge
        const priorityConfig = priorityMap[memo.priority] || priorityMap[5];
        const priorityLozenge = createLozenge(priorityConfig.text, priorityConfig.appearance);
        meta.appendChild(createMetaItem('Priority', priorityLozenge));

        // Status lozenge
        const statusConfig = statusMap[memo.status || 'active'] || statusMap['active'];
        const statusLozenge = createLozenge(statusConfig.text, statusConfig.appearance);
        meta.appendChild(createMetaItem('Status', statusLozenge));

        // Category
        const categoryValue = document.createElement('span');
        categoryValue.textContent = memo.category || 'default';
        meta.appendChild(createMetaItem('Category', categoryValue));

        const content = document.createElement('p');
        content.textContent = memo.text || memo.content || '';

        article.appendChild(meta);
        article.appendChild(content);

        const tags = Array.isArray(memo.tags) ? memo.tags : [];
        if (tags.length) {
            const tagList = document.createElement('div');
            tagList.className = 'memo-tags';
            tags.forEach((tag) => {
                const chip = document.createElement('span');
                chip.className = 'memo-tag';
                chip.textContent = tag;
                tagList.appendChild(chip);
            });
            article.appendChild(tagList);
        }

        const actions = document.createElement('div');
        actions.className = 'memo-actions';

        const deleteButton = document.createElement('button');
        deleteButton.type = 'button';
        deleteButton.className = 'btn btn-danger btn-sm';
        deleteButton.dataset.action = 'delete';
        deleteButton.dataset.memoId = memo.id;
        deleteButton.textContent = 'Delete memo';

        actions.appendChild(deleteButton);
        article.appendChild(actions);

        return article;
    };

    const renderPagination = (totalItems) => {
        paginationContainer.innerHTML = '';
        const totalPages = Math.ceil(totalItems / state.itemsPerPage);
        if (totalPages <= 1) return;

        const createButton = (text, page, isDisabled = false, isActive = false) => {
            const button = document.createElement('button');
            button.textContent = text;
            button.dataset.page = page;
            button.disabled = isDisabled;
            if (isActive) button.classList.add('active');
            return button;
        };

        // Previous button
        paginationContainer.appendChild(createButton('Prev', state.currentPage - 1, state.currentPage === 1));

        // Page numbers
        for (let i = 1; i <= totalPages; i++) {
            paginationContainer.appendChild(createButton(i, i, false, i === state.currentPage));
        }

        // Next button
        paginationContainer.appendChild(createButton('Next', state.currentPage + 1, state.currentPage === totalPages));
    };

    const renderMemos = () => {
        memoList.innerHTML = '';
        const source = state.filteredMemos.length ? state.filteredMemos : state.memos;

        if (!source.length) {
            const emptyState = document.createElement('div');
            emptyState.className = 'empty-state';

            const image = document.createElement('div');
            image.className = 'empty-state-image';
            image.textContent = '📝'; // Placeholder icon

            const title = document.createElement('h3');
            title.className = 'empty-state-title';
            title.textContent = 'No memos yet';

            const description = document.createElement('p');
            description.className = 'empty-state-description';
            description.textContent = 'Your created memos will appear here. Why not create your first one?';

            const button = document.createElement('button');
            button.className = 'btn btn-primary';
            button.textContent = 'Create Memo';
            button.onclick = () => document.getElementById('memo-text').focus();

            emptyState.appendChild(image);
            emptyState.appendChild(title);
            emptyState.appendChild(description);
            emptyState.appendChild(button);
            memoList.appendChild(emptyState);

            renderPagination(0);
            return;
        }

        const startIndex = (state.currentPage - 1) * state.itemsPerPage;
        const endIndex = startIndex + state.itemsPerPage;
        const paginatedMemos = source.slice(startIndex, endIndex);

        paginatedMemos.forEach((memo) => {
            memoList.appendChild(renderMemo(memo));
        });

        renderPagination(source.length);
    };

    const storeToken = (token) => {
        state.token = token;
        sessionStorage.setItem('memo_web_token', token);
    };

    const handleLogin = async (event) => {
        event.preventDefault();
        showStatus('');

        const formData = new FormData(loginForm);
        const username = String(formData.get('username') || '').trim();
        const password = String(formData.get('password') || '');

        if (!username || !password) {
            showStatus('Username and password are required.');
            return;
        }

        try {
            const response = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password }),
                credentials: hostsRequireSecureCookies ? 'include' : 'same-origin',
            });

            if (!response.ok) {
                const payload = await response.json().catch(() => ({}));
                showStatus(payload.message || 'Sign-in failed. Check credentials.');
                return;
            }

            const payload = await response.json();
            if (!payload.token) {
                showStatus('Authentication response did not include a token.');
                return;
            }

            storeToken(payload.token);
            loginSection.parentElement.hidden = true;
            if (appContainer) appContainer.hidden = false;
            showStatus('Signed in successfully.', false);
            await Promise.all([loadMemos(), loadStats()]);
            initialiseRealtime();
        } catch (error) {
            console.error(error);
            showStatus('Unable to sign in. Check network connection.');
        }
    };

    const loadMemos = async () => {
        const response = await authenticatedFetch('/api/memos');
        if (!response) {
            return;
        }
        const payload = await response.json();
        state.memos = Array.isArray(payload.memos) ? payload.memos : [];
        state.filteredMemos = [];
        renderMemos();
    };

    const loadStats = async () => {
        const response = await authenticatedFetch('/api/stats');
        if (!response) {
            return;
        }
        state.stats = await response.json();
        renderStats();
    };

    const createMemo = async (event) => {
        event.preventDefault();
        showStatus('');

        const formData = new FormData(memoForm);
        const text = String(formData.get('memo-text') || '').trim();
        if (!text) {
            showStatus('Memo text is required.');
            return;
        }

        const tagsRaw = String(formData.get('memo-tags') || '');
        const tags = tagsRaw
            .split(',')
            .map((tag) => tag.trim())
            .filter(Boolean);

        const body = {
            text,
            type: formData.get('memo-type') || 'note',
            priority: Number(formData.get('memo-priority') || 5),
            category: String(formData.get('memo-category') || 'default').trim() || 'default',
            tags,
        };

        const response = await authenticatedFetch('/api/memos', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });

        if (!response) {
            return;
        }

        if (!response.ok) {
            const payload = await response.json().catch(() => ({}));
            showStatus(payload.message || 'Failed to create memo.');
            return;
        }

        const memo = await response.json();
        state.memos.unshift(memo);
        state.filteredMemos = [];
        memoForm.reset();
        renderMemos();
        loadStats();
        showStatus('Memo created successfully.', false);
    };

    const showModal = (title, message) => {
        return new Promise((resolve) => {
            modalTitle.textContent = title;
            modalBody.innerHTML = `<p>${message}</p>`;
            modalContainer.hidden = false;

            const confirmHandler = () => {
                modalContainer.hidden = true;
                resolve(true);
                cleanup();
            };

            const cancelHandler = () => {
                modalContainer.hidden = true;
                resolve(false);
                cleanup();
            };

            const cleanup = () => {
                modalConfirm.removeEventListener('click', confirmHandler);
                modalCancel.removeEventListener('click', cancelHandler);
                modalClose.removeEventListener('click', cancelHandler);
            };

            modalConfirm.addEventListener('click', confirmHandler, { once: true });
            modalCancel.addEventListener('click', cancelHandler, { once: true });
            modalClose.addEventListener('click', cancelHandler, { once: true });
        });
    };

    const deleteMemo = async (memoId) => {
        if (!memoId) {
            return;
        }

        const confirmed = await showModal('Delete Memo', 'Are you sure you want to delete this memo? This action cannot be undone.');
        if (!confirmed) {
            return;
        }

        const response = await authenticatedFetch(`/api/memos/${memoId}`, {
            method: 'DELETE',
        });

        if (!response) {
            return;
        }

        if (response.status !== 204) {
            const payload = await response.json().catch(() => ({}));
            showStatus(payload.message || 'Failed to delete memo.');
            return;
        }

        state.memos = state.memos.filter((memo) => memo.id !== memoId);
        state.filteredMemos = state.filteredMemos.filter((memo) => memo.id !== memoId);
        renderMemos();
        loadStats();
    };

    const executeSearch = async (event) => {
        if (event) {
            event.preventDefault();
        }
        const query = searchInput.value.trim();
        const mode = searchType.value;

        if (query.length > MAX_SEARCH_LENGTH) {
            showStatus(`Search text must be ${MAX_SEARCH_LENGTH} characters or fewer.`);
            return;
        }

        const params = new URLSearchParams();
        params.set('type', mode);
        if (query) {
            params.set('q', query);
        }

        const selectedStatuses = Array.from(statusFilter?.selectedOptions || []).map((option) => option.value).filter(Boolean);
        if (selectedStatuses.length) {
            params.set('status', selectedStatuses.join(','));
        }

        const selectedPriorities = Array.from(priorityFilter?.selectedOptions || []).map((option) => option.value).filter(Boolean);
        if (selectedPriorities.length) {
            params.set('priority', selectedPriorities.join(','));
        }

        const categoryValue = (categoryFilter?.value || '').trim();
        if (categoryValue) {
            params.set('category', categoryValue);
        }

        const tagsValue = (tagsFilter?.value || '').split(',').map((tag) => tag.trim()).filter(Boolean);
        if (tagsValue.length) {
            tagsValue.forEach((tag) => params.append('tags', tag));
        }

        if (createdFromInput?.value) {
            params.set('created_from', createdFromInput.value);
        }

        if (createdToInput?.value) {
            params.set('created_to', createdToInput.value);
        }

        const response = await authenticatedFetch(`/api/search?${params.toString()}`);
        if (!response) {
            return;
        }

        if (!response.ok) {
            const payload = await response.json().catch(() => ({}));
            showStatus(payload.message || 'Search failed.');
            return;
        }

        const payload = await response.json();
        const results = Array.isArray(payload.results) ? payload.results : [];
        state.filteredMemos = results.map((item) => item.memo || item).filter(Boolean);
        renderMemos();
    };

    const clearSearch = () => {
        searchInput.value = '';
        Array.from(statusFilter?.options || []).forEach((option) => {
            option.selected = false;
        });
        Array.from(priorityFilter?.options || []).forEach((option) => {
            option.selected = false;
        });
        if (categoryFilter) {
            categoryFilter.value = '';
        }
        if (tagsFilter) {
            tagsFilter.value = '';
        }
        if (createdFromInput) {
            createdFromInput.value = '';
        }
        if (createdToInput) {
            createdToInput.value = '';
        }
        state.filteredMemos = [];
        renderMemos();
    };

    const initialiseRealtime = () => {
        if (!window.io || state.socket) {
            return;
        }
        if (!state.token) {
            return;
        }

        const socket = window.io({
            transports: ['websocket', 'polling'],
            query: { token: `Bearer ${state.token}` },
        });
        state.socket = socket;

        socket.on('memo_created', (memo) => {
            if (!memo || !memo.id) {
                return;
            }
            const exists = state.memos.find((item) => item.id === memo.id);
            if (!exists) {
                state.memos.unshift(memo);
                renderMemos();
            }
            loadStats();
        });

        socket.on('memo_updated', (memo) => {
            if (!memo || !memo.id) {
                return;
            }
            state.memos = state.memos.map((item) => (item.id === memo.id ? memo : item));
            state.filteredMemos = state.filteredMemos.map((item) => (item.id === memo.id ? memo : item));
            renderMemos();
        });

        socket.on('memo_deleted', (payload) => {
            const memoId = payload && payload.id;
            if (!memoId) {
                return;
            }
            state.memos = state.memos.filter((item) => item.id !== memoId);
            state.filteredMemos = state.filteredMemos.filter((item) => item.id !== memoId);
            renderMemos();
            loadStats();
        });

        socket.on('connected', (payload) => {
            if (payload && payload.message) {
                showStatus(payload.message, false);
            }
        });

        socket.on('connect_error', (error) => {
            console.error('Socket connection error', error);
            showStatus('Real-time channel unavailable. Check network or credentials.');
        });

        socket.on('disconnect', (reason) => {
            console.warn('Socket disconnected', reason);
        });
    };

    memoList.addEventListener('click', (event) => {
        const target = event.target;
        if (!(target instanceof HTMLElement)) {
            return;
        }
        const action = target.dataset.action;
        if (action === 'delete') {
            deleteMemo(target.dataset.memoId);
        }
    });

    loginForm.addEventListener('submit', handleLogin);
    memoForm.addEventListener('submit', createMemo);
    searchForm.addEventListener('submit', executeSearch);
    clearSearchButton.addEventListener('click', clearSearch);

    paginationContainer.addEventListener('click', (event) => {
        const target = event.target;
        if (target.tagName === 'BUTTON' && !target.disabled) {
            const page = parseInt(target.dataset.page, 10);
            if (page) {
                state.currentPage = page;
                renderMemos();
            }
        }
    });

    if (searchToggle && searchSection) {
        searchToggle.addEventListener('click', () => {
            const isExpanded = searchToggle.getAttribute('aria-expanded') === 'true';
            searchToggle.setAttribute('aria-expanded', !isExpanded);
            searchSection.classList.toggle('collapsed');
            const icon = searchToggle.querySelector('.toggle-icon');
            if (icon) {
                icon.textContent = isExpanded ? '+' : '-';
            }
        });
    }

    const storedToken = sessionStorage.getItem('memo_web_token');
    if (storedToken) {
        storeToken(storedToken);
        loginSection.parentElement.hidden = true;
        if (appContainer) appContainer.hidden = false;
        Promise.all([loadMemos(), loadStats()]).then(initialiseRealtime).catch((error) => {
            console.error(error);
            resetSession();
        });
    }

    // Tooltip handler
    let tooltipElement;
    document.addEventListener('mouseover', (event) => {
        const target = event.target.closest('[data-tooltip]');
        if (!target) return;

        const tooltipText = target.dataset.tooltip;
        if (!tooltipText) return;

        tooltipElement = document.createElement('div');
        tooltipElement.className = 'tooltip';
        tooltipElement.textContent = tooltipText;
        document.body.appendChild(tooltipElement);

        const targetRect = target.getBoundingClientRect();
        const tooltipRect = tooltipElement.getBoundingClientRect();

        let top = targetRect.top - tooltipRect.height - 8;
        let left = targetRect.left + (targetRect.width / 2) - (tooltipRect.width / 2);

        if (top < 0) {
            top = targetRect.bottom + 8;
        }

        tooltipElement.style.left = `${left}px`;
        tooltipElement.style.top = `${top}px`;
        tooltipElement.style.opacity = '1';
    });

    document.addEventListener('mouseout', (event) => {
        const target = event.target.closest('[data-tooltip]');
        if (target && tooltipElement) {
            tooltipElement.remove();
            tooltipElement = null;
        }
    });

    // Keyboard shortcuts
    document.addEventListener('keydown', (event) => {
        // Ignore shortcuts if user is typing in an input field, unless it's a specific combo
        const isTyping = event.target.matches('input, textarea, select');

        if (event.key === '/' && !isTyping) {
            event.preventDefault();
            searchInput.focus();
        }

        if (event.key === 'c' && !isTyping) {
            event.preventDefault();
            document.getElementById('memo-text').focus();
        }

        if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
            const activeForm = document.activeElement.closest('form');
            if (activeForm) {
                event.preventDefault();
                activeForm.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
            }
        }
    });
})();
