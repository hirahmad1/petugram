const form = document.getElementById("match-form");
const input = document.getElementById("ingredients");
const ingredientPillsEl = document.getElementById("ingredient-pills");
const statusEl = document.getElementById("status");
const summaryEl = document.getElementById("summary");
const resultsEl = document.getElementById("results");
const submitBtn = document.getElementById("submit-btn");
const voiceBtn = document.getElementById("voice-btn");
const voiceHint = document.getElementById("voice-hint");

const USER_KEY = "petugram_session";
const THEME_KEY = "petugram_theme";
const FRIDGE_NOTIFY_KEY = "petugram_fridge_notify";
const FRIDGE_NOTIFIED_KEY = "petugram_fridge_notified";
const MEAL_PLAN_SESSION_KEY = "petugram_meal_plan";
const GROCERY_CHECKED_KEY = "petugram_grocery_checked";
let session = JSON.parse(localStorage.getItem(USER_KEY) || "null");
let userId = session?.user_id || null;
let userRole = session?.role || "guest";
let authMode = "login";

let lastRecipes = [];
let favoriteRecipeIds = new Set();
let mongoAvailable = false;
let pendingShoppingMissing = null;
let fridgeNotifyTimer = null;
let profileViewUserId = null;
let profileTab = "posts";
let profileEditOpen = false;
let currentProfileData = null;
let postsView = "trending";
let postComposeType = "post";
let notifyPollTimer = null;
let notifyVisibilityBound = false;
let userSearchTimer = null;
let msgActiveConversationId = null;
let msgActivePeer = null;
let msgLastThreadKey = "";
let msgPollTimer = null;
let msgUnreadTimer = null;
let msgUserSearchTimer = null;
let msgPendingFile = null;
let msgPendingKind = null;
let msgPendingPreviewUrl = null;
let msgVoiceRecorder = null;
let msgVoiceChunks = [];
let msgVoiceStream = null;
let msgVoiceTimer = null;
let msgVoiceStartedAt = 0;
let mealPlanDays = 3;
let currentMealPlan = null;
let currentGrocery = null;
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let listening = false;

function escapeHtml(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function escapeAttr(str) {
  return escapeHtml(str).replaceAll("'", "&#39;");
}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail;
    const message = Array.isArray(detail)
      ? detail.map((d) => d.msg || String(d)).join(", ")
      : detail || data.message || `Request failed (${res.status})`;
    throw new Error(message);
  }
  return data;
}

function saveSession(user) {
  session = user;
  userId = user.user_id;
  userRole = user.role || "user";
  profileViewUserId = user.user_id;
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

function clearSession() {
  session = null;
  userId = null;
  userRole = "guest";
  profileViewUserId = null;
  msgActiveConversationId = null;
  msgActivePeer = null;
  msgLastThreadKey = "";
  stopMessageThreadPolling();
  stopMessageUnreadPolling();
  localStorage.removeItem(USER_KEY);
}

function setStatus(el, message, isError = false) {
  if (!el) return;
  el.hidden = !message;
  el.textContent = message || "";
  el.classList.toggle("error", isError);
  if (message) el.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function applyTheme(mode) {
  const isDay = mode === "day";
  document.body.classList.toggle("day", isDay);
  document.body.classList.toggle("night", !isDay);
  const toggle = document.getElementById("theme-toggle");
  if (toggle) {
    toggle.setAttribute("aria-label", isDay ? "Switch to night mode" : "Switch to day mode");
    toggle.title = isDay ? "Switch to night" : "Switch to day";
  }
  localStorage.setItem(THEME_KEY, isDay ? "day" : "night");
}

function initTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  applyTheme(saved === "day" ? "day" : "night");
  document.getElementById("theme-toggle")?.addEventListener("click", () => {
    applyTheme(document.body.classList.contains("day") ? "night" : "day");
  });
}

function initHeaderScroll() {
  const header = document.getElementById("site-header");
  if (!header) return;
  const onScroll = () => header.classList.toggle("scrolled", window.scrollY > 24);
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });
}

function updateHeroCta() {
  const cta = document.getElementById("hero-cta");
  if (!cta) return;
  cta.textContent = "Open fridge";
  cta.setAttribute("href", "#pantry");
  cta.dataset.panel = "pantry";
  cta.setAttribute("aria-label", "Open digital fridge");
}

function showPanel(name, opts = {}) {
  const hero = document.getElementById("home-hero");
  document.querySelectorAll(".panel").forEach((panel) => {
    panel.hidden = panel.id !== name;
  });
  if (hero) hero.hidden = name !== "pantry";
  document.body.classList.toggle("on-profile", name === "profile");
  document.body.classList.toggle("on-messages", name === "messages");
  document.body.classList.toggle("on-matcher", name === "matcher");
  if (name !== "posts") document.body.classList.remove("on-reels");
  document.body.classList.toggle("slim-chrome", name !== "pantry");
  document.querySelectorAll(".nav-link[data-panel]").forEach((link) => {
    const on = link.dataset.panel === name;
    link.classList.toggle("active", on);
    if (on && window.matchMedia("(max-width: 900px)").matches) {
      link.scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" });
    }
  });
  const activePanel = document.getElementById(name);
  if (activePanel && !opts.skipEnter) {
    activePanel.classList.remove("panel-enter");
    void activePanel.offsetWidth;
    activePanel.classList.add("panel-enter");
  }
  updateHeroCta();
  if (location.hash !== `#${name}`) {
    history.replaceState(null, "", `#${name}`);
  }

  // Scroll only when explicitly requested — never jump on normal nav/icon clicks.
  if (opts.scrollTo) {
    requestAnimationFrame(() => {
      document.getElementById(opts.scrollTo)?.scrollIntoView({ behavior: "smooth", block: "start" });
      if (opts.focus) {
        document.getElementById(opts.focus)?.focus({ preventScroll: true });
      }
    });
  } else if (opts.scrollTop) {
    window.scrollTo({ top: 0, behavior: "auto" });
  } else if (opts.focus) {
    requestAnimationFrame(() => {
      document.getElementById(opts.focus)?.focus({ preventScroll: true });
    });
  }

  if (name === "pantry") loadPantry();
  if (name === "meal-plan") loadMealPlanPanel();
  if (name === "posts") loadPosts();
  if (name === "restaurants") loadRestaurantsPanel();
  if (name === "surplus") loadSurplusPanel();
  if (name === "messages") loadMessagesPanel();
  if (name === "profile") loadProfile();
  if (name === "admin") loadAdmin();
  if (name !== "messages") stopMessageThreadPolling();
}

function initNav() {
  document.querySelectorAll(".nav-link, .cta-row [data-panel], .inline-link[data-panel], a.brand[data-panel]").forEach((link) => {
    link.addEventListener("click", (e) => {
      e.preventDefault();
      if (link.dataset.panel === "profile" && userId && link.classList.contains("nav-link")) {
        profileViewUserId = userId;
      }
      const panel = link.dataset.panel;
      showPanel(panel, { scrollTop: true });
    });
  });

  const hash = location.hash.slice(1);
  const valid = ["matcher", "pantry", "meal-plan", "posts", "restaurants", "surplus", "messages", "profile", "admin"];
  if (hash && valid.includes(hash)) {
    showPanel(hash, { skipScroll: true });
  } else {
    showPanel("pantry", { skipScroll: true });
  }

  window.addEventListener("hashchange", () => {
    const panel = location.hash.slice(1);
    if (panel && document.getElementById(panel)) showPanel(panel, { skipScroll: true });
  });
}

let storyViewerState = null;
let storyProgressTimer = null;

function renderNavUserAvatar() {
  const btn = document.getElementById("auth-user");
  const avatar = document.getElementById("nav-user-avatar");
  const nameEl = document.getElementById("nav-user-name");
  if (!btn || !avatar) return;
  if (!session?.username) {
    btn.hidden = true;
    avatar.innerHTML = "";
    avatar.classList.remove("has-story", "story-seen");
    btn.classList.remove("has-story", "story-seen");
    if (nameEl) nameEl.textContent = "";
    return;
  }
  const label = `${session.username}${userRole === "admin" ? " · Admin" : ""}`;
  const initials = profileInitials(session.username);
  const hasStory = !!session.has_active_story;
  const seen = !!session.story_seen;
  avatar.innerHTML = session.avatar_url
    ? `<img src="${escapeAttr(session.avatar_url)}" alt="" />`
    : `<span>${escapeHtml(initials)}</span>`;
  avatar.classList.toggle("has-story", hasStory);
  avatar.classList.toggle("story-seen", hasStory && seen);
  btn.classList.toggle("has-story", hasStory);
  btn.classList.toggle("story-seen", hasStory && seen);
  btn.hidden = false;
  btn.title = hasStory ? `View story · ${label}` : `Open profile · ${label}`;
  btn.setAttribute("aria-label", hasStory ? `View ${session.username}'s story` : `Open profile for ${session.username}`);
  if (nameEl) nameEl.textContent = label;
}

function updateAuthUi() {
  const logoutBtn = document.getElementById("logout-btn");
  const loginBtn = document.getElementById("login-open-btn");
  const adminLink = document.querySelector(".nav-link.admin-only");

  if (session?.username) {
    renderNavUserAvatar();
    if (logoutBtn) logoutBtn.hidden = false;
    if (loginBtn) loginBtn.hidden = true;
  } else {
    renderNavUserAvatar();
    if (logoutBtn) logoutBtn.hidden = true;
    if (loginBtn) loginBtn.hidden = false;
  }
  if (adminLink) adminLink.hidden = userRole !== "admin";
  const notifyWrap = document.getElementById("notify-wrap");
  if (notifyWrap) notifyWrap.hidden = !userId;
  if (!userId || !mongoAvailable) updateFridgeAlertBadge(0);
  else if (!fridgeNotifyTimer) pollFridgeAlerts();
  updateMealPlanActionVisibility();
  updatePostsAuthUi();
  setMessagesVisibility(!!userId);
  if (userId && mongoAvailable) {
    loadNotifications();
    loadMsgUnreadBadge();
    startMessageUnreadPolling();
  } else {
    stopMessageUnreadPolling();
    const badge = document.getElementById("msg-nav-badge");
    if (badge) badge.hidden = true;
    closeActiveConversation();
  }
}

let authProviders = { google: { enabled: false }, facebook: { enabled: false } };
let googleBtnRendered = false;
let facebookSdkReady = false;

function validateUsernameClient(username, { forRegister = false } = {}) {
  const value = String(username || "").trim().toLowerCase();
  if (value.length < 3) return "Username must be at least 3 characters";
  if (value.length > 24) return "Username must be at most 24 characters";
  if (!/^[a-z][a-z0-9_]{2,23}$/.test(value)) {
    return "Username must start with a letter and use only letters, numbers, and underscores";
  }
  if (forRegister && ["admin", "administrator", "root", "system", "support", "petugram"].includes(value)) {
    return "That username is reserved";
  }
  return "";
}

function validatePasswordClient(password, { forRegister = false } = {}) {
  const value = String(password || "");
  if (forRegister) {
    if (value.length < 8) return "Password must be at least 8 characters";
    if (value.length > 128) return "Password must be at most 128 characters";
    if (value.trim() !== value) return "Password cannot start or end with spaces";
    if (!/[A-Za-z]/.test(value)) return "Password must include at least one letter";
    if (!/\d/.test(value)) return "Password must include at least one number";
  } else if (value.length < 6) {
    return "Password must be at least 6 characters";
  }
  return "";
}

function setAuthError(message = "") {
  const error = document.getElementById("auth-error");
  if (!error) return;
  if (message) {
    error.hidden = false;
    error.textContent = message;
  } else {
    error.hidden = true;
    error.textContent = "";
  }
}

function finishAuthSuccess(user) {
  saveSession(user);
  updateAuthUi();
  document.getElementById("auth-dialog")?.close();
  const profilePanel = document.getElementById("profile");
  if (profilePanel && !profilePanel.hidden) loadProfile();
  const pantryPanel = document.getElementById("pantry");
  if (pantryPanel && !pantryPanel.hidden) loadPantry();
  const postsPanel = document.getElementById("posts");
  if (postsPanel && !postsPanel.hidden) loadPosts();
  const messagesPanel = document.getElementById("messages");
  if (messagesPanel && !messagesPanel.hidden) loadMessagesPanel();
  if (document.getElementById("admin") && !document.getElementById("admin").hidden) {
    loadAdmin();
  }
  showToast(`Welcome, ${user.username}!`, false, { rich: true, variant: "success", title: "Signed in", duration: 2800 });
}

function openAuthDialog(mode = "login") {
  authMode = mode;
  const dialog = document.getElementById("auth-dialog");
  if (!dialog) return;
  const isLogin = mode === "login";
  document.getElementById("auth-title").textContent = isLogin ? "Log in" : "Create account";
  document.getElementById("auth-subtitle").textContent = isLogin
    ? "Welcome back — cook what you have."
    : "Join Petugram and start saving leftovers.";
  document.getElementById("auth-submit").textContent = isLogin ? "Log in" : "Create account";
  document.getElementById("auth-toggle").textContent = isLogin
    ? "Create account"
    : "Already have an account? Log in";
  const confirmWrap = document.getElementById("auth-confirm-wrap");
  const confirmInput = document.getElementById("auth-password-confirm");
  const passwordInput = document.getElementById("auth-password");
  const usernameHint = document.getElementById("auth-username-hint");
  const passwordHint = document.getElementById("auth-password-hint");
  if (confirmWrap) confirmWrap.hidden = isLogin;
  if (confirmInput) {
    confirmInput.required = !isLogin;
    confirmInput.value = "";
  }
  if (passwordInput) {
    passwordInput.autocomplete = isLogin ? "current-password" : "new-password";
    passwordInput.minLength = isLogin ? 6 : 8;
  }
  if (usernameHint) usernameHint.hidden = isLogin;
  if (passwordHint) passwordHint.hidden = isLogin;
  setAuthError("");
  dialog.showModal();
  renderSocialAuthButtons();
  document.getElementById("auth-username")?.focus();
}

function requireLogin(actionLabel = "use this feature") {
  if (!userId) {
    setStatus(statusEl, `Log in or register to ${actionLabel}.`, true);
    openAuthDialog("login");
    return false;
  }
  return true;
}

async function handleAuthSubmit(e) {
  e.preventDefault();
  const username = document.getElementById("auth-username").value.trim();
  const password = document.getElementById("auth-password").value;
  const confirm = document.getElementById("auth-password-confirm")?.value || "";
  const forRegister = authMode === "register";
  const usernameError = validateUsernameClient(username, { forRegister });
  if (usernameError) return setAuthError(usernameError);
  const passwordError = validatePasswordClient(password, { forRegister });
  if (passwordError) return setAuthError(passwordError);
  if (forRegister && password !== confirm) return setAuthError("Passwords do not match");

  const path = forRegister ? "/api/auth/register" : "/api/auth/login";
  const submitBtn = document.getElementById("auth-submit");
  if (submitBtn) submitBtn.disabled = true;
  setAuthError("");
  try {
    const data = await api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: username.toLowerCase(), password }),
    });
    finishAuthSuccess(data.user);
  } catch (err) {
    setAuthError(err.message || "Authentication failed");
  } finally {
    if (submitBtn) submitBtn.disabled = false;
  }
}

async function completeOAuthLogin(provider, credential) {
  setAuthError("");
  try {
    const data = await api("/api/auth/oauth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider, credential }),
    });
    finishAuthSuccess(data.user);
  } catch (err) {
    setAuthError(err.message || `${provider} sign-in failed`);
  }
}

function handleGoogleCredentialResponse(response) {
  if (!response?.credential) {
    setAuthError("Google sign-in was cancelled");
    return;
  }
  completeOAuthLogin("google", response.credential);
}

function renderGoogleButton() {
  const host = document.getElementById("google-signin-btn");
  if (!host) return;
  host.innerHTML = "";
  if (!authProviders.google?.enabled || !authProviders.google?.client_id) {
    host.hidden = true;
    return;
  }
  host.hidden = false;
  if (!window.google?.accounts?.id) return;
  window.google.accounts.id.initialize({
    client_id: authProviders.google.client_id,
    callback: handleGoogleCredentialResponse,
    auto_select: false,
    cancel_on_tap_outside: true,
  });
  window.google.accounts.id.renderButton(host, {
    theme: "outline",
    size: "large",
    shape: "pill",
    text: "continue_with",
    width: 280,
  });
  googleBtnRendered = true;
}

function loadFacebookSdk(appId) {
  if (facebookSdkReady || !appId) return Promise.resolve();
  return new Promise((resolve) => {
    window.fbAsyncInit = function fbAsyncInit() {
      window.FB.init({
        appId,
        cookie: true,
        xfbml: false,
        version: "v21.0",
      });
      facebookSdkReady = true;
      resolve();
    };
    if (document.getElementById("facebook-jssdk")) {
      if (window.FB) {
        facebookSdkReady = true;
        resolve();
      }
      return;
    }
    const script = document.createElement("script");
    script.id = "facebook-jssdk";
    script.src = "https://connect.facebook.net/en_US/sdk.js";
    script.async = true;
    script.defer = true;
    document.body.appendChild(script);
  });
}

async function startFacebookLogin() {
  if (!authProviders.facebook?.enabled) {
    setAuthError("Facebook sign-in is not configured");
    return;
  }
  try {
    await loadFacebookSdk(authProviders.facebook.app_id);
    if (!window.FB) throw new Error("Facebook SDK failed to load");
    window.FB.login(
      (response) => {
        const token = response?.authResponse?.accessToken;
        if (!token) {
          setAuthError("Facebook sign-in was cancelled");
          return;
        }
        completeOAuthLogin("facebook", token);
      },
      { scope: "public_profile,email" }
    );
  } catch (err) {
    setAuthError(err.message || "Facebook sign-in failed");
  }
}

function renderSocialAuthButtons() {
  const wrap = document.getElementById("auth-social");
  const fbBtn = document.getElementById("facebook-signin-btn");
  const googleEnabled = !!authProviders.google?.enabled;
  const facebookEnabled = !!authProviders.facebook?.enabled;
  if (wrap) wrap.hidden = !(googleEnabled || facebookEnabled);
  if (fbBtn) {
    fbBtn.hidden = !facebookEnabled;
  }
  if (googleEnabled) {
    if (window.google?.accounts?.id) renderGoogleButton();
    else {
      // GIS script loads async
      const wait = setInterval(() => {
        if (window.google?.accounts?.id) {
          clearInterval(wait);
          renderGoogleButton();
        }
      }, 200);
      setTimeout(() => clearInterval(wait), 8000);
    }
  }
}

async function loadAuthProviders() {
  try {
    const data = await api("/api/auth/providers");
    authProviders = data.providers || authProviders;
    if (authProviders.facebook?.enabled && authProviders.facebook.app_id) {
      loadFacebookSdk(authProviders.facebook.app_id).catch(() => {});
    }
  } catch {
    authProviders = { google: { enabled: false }, facebook: { enabled: false } };
  }
}

function initAuth() {
  document.getElementById("login-open-btn")?.addEventListener("click", () => openAuthDialog("login"));
  document.getElementById("profile-login-btn")?.addEventListener("click", () => openAuthDialog("login"));
  document.getElementById("pantry-login-btn")?.addEventListener("click", () => openAuthDialog("login"));
  document.getElementById("posts-login-btn")?.addEventListener("click", () => openAuthDialog("login"));
  document.getElementById("auth-user")?.addEventListener("click", () => {
    if (!userId) {
      openAuthDialog("login");
      return;
    }
    if (session?.has_active_story) {
      openUserStory(userId);
      return;
    }
    profileViewUserId = userId;
    showPanel("profile");
    loadProfile();
  });
  document.getElementById("story-upload-input")?.addEventListener("change", (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (file) uploadStory(file);
  });
  document.getElementById("story-viewer-close")?.addEventListener("click", closeStoryViewerAndRefresh);
  document.getElementById("story-viewer")?.addEventListener("cancel", (e) => {
    e.preventDefault();
    closeStoryViewerAndRefresh();
  });
  document.getElementById("story-nav-prev")?.addEventListener("click", () => {
    if (!storyViewerState) return;
    if (storyViewerState.index > 0) showStoryAt(storyViewerState.index - 1);
  });
  document.getElementById("story-nav-next")?.addEventListener("click", () => {
    if (!storyViewerState) return;
    if (storyViewerState.index + 1 < storyViewerState.stories.length) showStoryAt(storyViewerState.index + 1);
    else closeStoryViewerAndRefresh();
  });
  document.getElementById("story-delete-btn")?.addEventListener("click", async () => {
    const story = storyViewerState?.stories?.[storyViewerState.index];
    if (!story?.story_id || !userId) return;
    try {
      await api(`/api/stories/${encodeURIComponent(story.story_id)}?user_id=${encodeURIComponent(userId)}`, {
        method: "DELETE",
      });
      storyViewerState.stories.splice(storyViewerState.index, 1);
      if (!storyViewerState.stories.length) closeStoryViewerAndRefresh();
      else showStoryAt(Math.min(storyViewerState.index, storyViewerState.stories.length - 1));
    } catch (err) {
      showToast(err.message, true);
    }
  });
  document.getElementById("story-sound-btn")?.addEventListener("click", (e) => {
    e.stopPropagation();
    const video = document.getElementById("story-viewer-video");
    if (!video || video.hidden) return;
    const nextMuted = !video.muted;
    setStorySoundMuted(nextMuted);
    if (!nextMuted) {
      video.play().catch(() => {});
    }
  });
  document.getElementById("story-views-btn")?.addEventListener("click", () => {
    openStoryViewersSheet();
  });
  document.getElementById("story-viewers-close")?.addEventListener("click", () => {
    closeStoryViewersSheet();
  });
  document.getElementById("story-viewers-list")?.addEventListener("click", (e) => {
    const row = e.target.closest(".story-viewer-row");
    if (!row?.dataset.userId) return;
    const target = row.dataset.userId;
    closeStoryViewerAndRefresh();
    profileViewUserId = target;
    showPanel("profile");
    loadProfile();
  });
  document.getElementById("delete-account-btn")?.addEventListener("click", openDeleteAccountDialog);
  document.getElementById("delete-account-form")?.addEventListener("submit", handleDeleteAccount);
  document.getElementById("delete-account-cancel")?.addEventListener("click", () => {
    document.getElementById("delete-account-dialog")?.close();
  });
  document.getElementById("facebook-signin-btn")?.addEventListener("click", startFacebookLogin);
  document.getElementById("logout-btn")?.addEventListener("click", () => {
    clearSession();
    updateAuthUi();
    loadPantry();
    loadPosts();
    loadMessagesPanel();
    loadProfile();
    loadAdmin();
  });
  document.getElementById("auth-toggle")?.addEventListener("click", () => {
    openAuthDialog(authMode === "login" ? "register" : "login");
  });
  document.getElementById("auth-close")?.addEventListener("click", () => {
    document.getElementById("auth-dialog")?.close();
  });
  document.getElementById("auth-form")?.addEventListener("submit", handleAuthSubmit);
  loadAuthProviders();
}

async function checkHealth() {
  try {
    const h = await api("/api/health");
    mongoAvailable = h.mongodb === true;
    const banner = document.getElementById("mongo-banner");
    if (!mongoAvailable && banner) {
      banner.hidden = false;
      banner.textContent =
        "MongoDB is offline. Start MongoDB locally for pantry, profile & badges.";
    } else if (banner) {
      banner.hidden = true;
    }
  } catch {
    mongoAvailable = false;
  }
  return mongoAvailable;
}

async function refreshSession() {
  if (!session?.user_id) return null;
  try {
    const data = await api(`/api/auth/me?user_id=${encodeURIComponent(session.user_id)}`);
    saveSession(data.user);
    return data.user;
  } catch {
    clearSession();
    return null;
  }
}

let lastSearchQuery = [];

const INGREDIENT_CATALOG = {
  Produce: ["tomato", "onion", "potato", "spinach", "carrot", "pepper", "garlic", "lemon", "mushroom", "cabbage", "cucumber", "zucchini", "lettuce", "broccoli"],
  Protein: ["chicken", "beef", "fish", "egg", "tofu", "shrimp", "lentil", "beans", "turkey", "salmon", "pork"],
  Dairy: ["milk", "cheese", "butter", "yogurt", "cream", "ghee", "mozzarella"],
  Grains: ["rice", "pasta", "bread", "flour", "oats", "noodles", "quinoa"],
  Pantry: ["oil", "salt", "sugar", "honey", "vinegar", "soy sauce", "cumin", "paprika", "basil", "oregano"],
};

function ingredientCategory(name) {
  const n = normalizeIngredientToken(name);
  if (INGREDIENT_CATEGORY_LOOKUP[n]) return INGREDIENT_CATEGORY_LOOKUP[n];
  for (const [cat, items] of Object.entries(INGREDIENT_CATALOG)) {
    if (items.some((item) => {
      const tok = normalizeIngredientToken(item);
      return tok === n || n.includes(tok) || tok.includes(n);
    })) {
      return cat;
    }
  }
  return "Other";
}

let INGREDIENT_CATEGORY_LOOKUP = {};

function parseIngredients(raw) {
  const trimmed = String(raw || "").trim();
  if (!trimmed) return [];
  if (!trimmed.includes(",") && !trimmed.includes("|") && !trimmed.includes("\n")) {
    return [trimmed];
  }
  return trimmed.split(/[,|\n]/).map((s) => s.trim()).filter(Boolean);
}

function normalizeIngredientToken(text) {
  let s = String(text || "").trim().toLowerCase();
  s = s.replace(/[^a-z0-9\s-]/g, " ").replace(/\s+/g, " ").trim();
  if (s.endsWith("ies") && s.length > 4) return s.slice(0, -3) + "y";
  if (s.endsWith("oes") && s.length > 4) return s.slice(0, -2);
  if (s.endsWith("s") && !s.endsWith("ss") && s.length > 3) return s.slice(0, -1);
  return s;
}

function rebuildIngredientLookup() {
  INGREDIENT_CATEGORY_LOOKUP = Object.fromEntries(
    Object.entries(INGREDIENT_CATALOG).flatMap(([category, items]) =>
      items.map((item) => [normalizeIngredientToken(item), category])
    )
  );
}
rebuildIngredientLookup();

function ingredientMatchesLeftover(leftover, recipeIng) {
  const u = normalizeIngredientToken(leftover);
  const r = normalizeIngredientToken(recipeIng);
  if (!u || !r) return false;
  if (u === r || u.includes(r) || r.includes(u)) return true;
  const ut = u.split(/\s+/).filter((p) => p.length > 1);
  const rt = r.split(/\s+/).filter((p) => p.length > 1);
  return ut.some((part) => rt.includes(part) || rt.some((rp) => part.includes(rp) || rp.includes(part)));
}

function recipeIngredientRows(recipe) {
  const fromMeasurements = (recipe.measurements || [])
    .filter((m) => m && m.ingredient)
    .map((m) => ({
      ingredient: String(m.ingredient).trim(),
      amount: String(m.amount || "as needed").trim(),
    }));
  if (fromMeasurements.length) return fromMeasurements;
  return (recipe.ingredients || []).map((ing) => ({
    ingredient: String(ing).trim(),
    amount: "as needed",
  }));
}

function buildIngredientPanel(recipe, userLeftovers, { compact = false } = {}) {
  const rows = recipeIngredientRows(recipe);
  if (!rows.length) return "";

  const leftovers = userLeftovers.length ? userLeftovers : recipe.matched_ingredients || [];
  const have = [];
  const need = [];

  for (const row of rows) {
    const matched =
      leftovers.some((l) => ingredientMatchesLeftover(l, row.ingredient)) ||
      (recipe.matched_ingredients || []).some((m) => ingredientMatchesLeftover(m, row.ingredient));
    const enriched = { ...row, category: ingredientCategory(row.ingredient) };
    (matched ? have : need).push(enriched);
  }

  const total = rows.length;
  const haveCount = have.length;
  const pct = total ? Math.round((haveCount / total) * 100) : 0;

  if (compact) {
    const recipeJson = escapeAttr(JSON.stringify(recipe));
    return `
      <div class="ingredient-panel ingredient-panel--compact">
        <div class="ingredient-panel-head">
          <h4 class="steps-heading">Ingredients</h4>
          <span class="ingredient-match-pill">${haveCount} of ${total} on hand</span>
        </div>
        <div class="ingredient-progress" role="presentation" aria-hidden="true">
          <div class="ingredient-progress-fill" style="width:${pct}%"></div>
        </div>
        <ul class="ingredient-preview-list">
          ${[
            ...have.map((row) => ({ ...row, status: "have" })),
            ...need.map((row) => ({ ...row, status: "need" })),
          ]
            .slice(0, 4)
            .map(
              (row) => `<li class="ingredient-preview-item ingredient-preview-item--${row.status}">
                <span>${pantryItemIcon(row.ingredient)}</span>
                <span>${escapeHtml(row.ingredient)}</span>
              </li>`
            )
            .join("")}
        </ul>
        <button type="button" class="btn ghost ingredient-view-all" data-recipe="${recipeJson}">View full ingredient list</button>
      </div>`;
  }

  const renderRow = (row, status) => `
    <tr class="ingredient-table-row ingredient-table-row--${status}">
      <td><span class="ingredient-row-icon" aria-hidden="true">${pantryItemIcon(row.ingredient)}</span></td>
      <td><span class="ingredient-row-name">${escapeHtml(row.ingredient)}</span></td>
      <td><span class="ingredient-row-amount">${escapeHtml(row.amount)}</span></td>
      <td><span class="ingredient-table-category">${escapeHtml(row.category || ingredientCategory(row.ingredient))}</span></td>
      <td><span class="ingredient-row-badge">${status === "have" ? "Have" : "Need"}</span></td>
    </tr>`;

  return `
    <div class="ingredient-panel ingredient-panel--full">
      <div class="ingredient-panel-head">
        <h4 class="steps-heading">Ingredients</h4>
        <span class="ingredient-match-pill">${haveCount} of ${total} from your fridge</span>
      </div>
      <div class="ingredient-progress" role="presentation" aria-hidden="true">
        <div class="ingredient-progress-fill" style="width:${pct}%"></div>
      </div>
      <div class="ingredient-table-wrap">
        <table class="ingredient-table">
          <thead>
            <tr>
              <th scope="col"></th>
              <th scope="col">Ingredient</th>
              <th scope="col">Amount</th>
              <th scope="col">Category</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            ${have.map((row) => renderRow(row, "have")).join("")}
            ${need.map((row) => renderRow(row, "need")).join("")}
          </tbody>
        </table>
      </div>
    </div>`;
}

function openRecipeIngredientsDialog(recipe) {
  const dialog = document.getElementById("recipe-ingredients-dialog");
  const title = document.getElementById("recipe-ingredients-title");
  const body = document.getElementById("recipe-ingredients-body");
  if (!dialog || !title || !body) return;
  title.textContent = recipe.name || "Recipe";
  body.innerHTML = buildIngredientPanel(recipe, lastSearchQuery, { compact: false });
  dialog.showModal();
}

function setIngredientsValue(items) {
  input.value = items.join(", ");
  renderIngredientPills();
}

function renderIngredientPills() {
  if (!ingredientPillsEl) return;
  const items = parseIngredients(input.value);
  if (!items.length) {
    ingredientPillsEl.hidden = true;
    ingredientPillsEl.innerHTML = "";
    return;
  }
  ingredientPillsEl.hidden = false;
  ingredientPillsEl.innerHTML = items
    .map(
      (item, idx) =>
        `<button type="button" class="ingredient-pill" data-index="${idx}" title="Remove ${escapeAttr(item)}">
          <span class="ingredient-pill-icon" aria-hidden="true">${pantryItemIcon(item)}</span>
          <span>${escapeHtml(item)}</span>
          <span class="ingredient-pill-remove" aria-hidden="true">×</span>
        </button>`
    )
    .join("");
  ingredientPillsEl.querySelectorAll(".ingredient-pill").forEach((btn) => {
    btn.addEventListener("click", () => {
      const next = parseIngredients(input.value);
      next.splice(Number(btn.dataset.index), 1);
      setIngredientsValue(next);
      input.focus();
    });
  });
}

function goalLabel(goal) {
  if (goal === "weight_gain") return "weight gain";
  if (goal === "weight_loss") return "weight loss";
  return goal || "";
}

function difficultyLabel(level) {
  if (level === "easy") return "Easy";
  if (level === "medium") return "Medium";
  if (level === "hard") return "Hard";
  return level || "";
}

function selectedFilter(name) {
  const el = form.querySelector(`input[name="${name}"]:checked, select[name="${name}"]`);
  if (!el || !el.value) return null;
  if (name === "max_time_min" || name === "max_calories") return Number(el.value);
  return el.value;
}

function collectMatchFilters() {
  const raw = {
    diet: selectedFilter("diet"),
    cuisine: selectedFilter("cuisine"),
    max_time_min: selectedFilter("max_time_min"),
    difficulty: selectedFilter("difficulty"),
    max_calories: selectedFilter("max_calories"),
  };
  return Object.fromEntries(Object.entries(raw).filter(([, value]) => value != null && value !== ""));
}

function formatActiveFilters(filters) {
  const parts = [];
  if (filters.cuisine) parts.push(filters.cuisine);
  if (filters.diet === "vegan") parts.push("vegan");
  if (filters.diet === "non-vegan") parts.push("non-vegan");
  if (filters.max_time_min) parts.push(`≤ ${filters.max_time_min} min`);
  if (filters.difficulty) parts.push(difficultyLabel(filters.difficulty));
  if (filters.max_calories) parts.push(`≤ ${filters.max_calories} kcal`);
  return parts.length ? ` · Filters: ${parts.join(", ")}` : "";
}

function addIngredientFromInput() {
  const addInput = document.getElementById("ingredient-add");
  const raw = addInput?.value.trim();
  if (!raw) return;
  const current = parseIngredients(input.value);
  const incoming = parseIngredients(raw);
  const merged = [...current];
  for (const item of incoming) {
    if (!merged.some((x) => x.toLowerCase() === item.toLowerCase())) merged.push(item);
  }
  setIngredientsValue(merged);
  if (addInput) addInput.value = "";
  addInput?.focus();
}

async function loadFridgeFromPantry() {
  if (!requireLogin("load pantry ingredients")) return;
  if (!mongoAvailable) {
    setStatus(statusEl, "Connect MongoDB to load pantry ingredients.", true);
    return;
  }
  try {
    const data = await api(`/api/pantry?user_id=${encodeURIComponent(userId)}`);
    const names = (data.items || []).map((item) => item.ingredient).filter(Boolean);
    if (!names.length) {
      setStatus(statusEl, "Your fridge is empty. Add items in the Fridge tab first.", true);
      return;
    }
    setIngredientsValue(names);
    setStatus(statusEl, `Loaded ${names.length} ingredient${names.length === 1 ? "" : "s"} from your fridge.`);
  } catch (err) {
    setStatus(statusEl, err.message, true);
  }
}

function planStatus(message, isError = false) {
  setStatus(document.getElementById("meal-plan-status"), message, isError);
}

function collectPlanFilters() {
  const num = (id) => {
    const v = document.getElementById(id)?.value;
    return v ? Number(v) : null;
  };
  const str = (id) => document.getElementById(id)?.value || null;
  return {
    cuisine: str("plan-filter-cuisine") || null,
    max_time_min: num("plan-filter-time"),
    difficulty: str("plan-filter-difficulty") || null,
    diet: str("plan-filter-diet") || null,
  };
}

function planIngredientsList() {
  return parseIngredients(document.getElementById("plan-ingredients")?.value || "");
}

function persistMealPlanSession(plan) {
  try {
    if (plan) sessionStorage.setItem(MEAL_PLAN_SESSION_KEY, JSON.stringify(plan));
    else sessionStorage.removeItem(MEAL_PLAN_SESSION_KEY);
  } catch {
    /* ignore */
  }
}

function readMealPlanSession() {
  try {
    return JSON.parse(sessionStorage.getItem(MEAL_PLAN_SESSION_KEY) || "null");
  } catch {
    return null;
  }
}

function updateMealPlanActionVisibility() {
  const hasPlan = !!(currentMealPlan?.days?.length);
  const regen = document.getElementById("plan-regenerate");
  const save = document.getElementById("plan-save");
  const del = document.getElementById("plan-delete");
  const refresh = document.getElementById("plan-grocery-refresh");
  if (regen) regen.hidden = !hasPlan;
  if (save) save.hidden = !(hasPlan && userId && mongoAvailable);
  if (del) del.hidden = !hasPlan;
  if (refresh) refresh.hidden = !hasPlan;
}

function readGroceryChecked() {
  try {
    return new Set(JSON.parse(localStorage.getItem(GROCERY_CHECKED_KEY) || "[]"));
  } catch {
    return new Set();
  }
}

function writeGroceryChecked(set) {
  try {
    localStorage.setItem(GROCERY_CHECKED_KEY, JSON.stringify([...set]));
  } catch {
    /* ignore */
  }
}

function syncFridgeShoppingPanel(grocery) {
  const panel = document.getElementById("shopping-panel");
  const list = document.getElementById("shopping-list");
  if (!panel || !list) return;
  const items = grocery?.items || [];
  if (!items.length) {
    panel.hidden = true;
    list.innerHTML = "";
    return;
  }
  panel.hidden = false;
  list.innerHTML = items
    .map(
      (i, idx) => `<article class="shopping-item">
        <span class="shopping-item-num">${idx + 1}</span>
        <div class="shopping-item-body">
          <strong>${escapeHtml(i.ingredient)}</strong>
          <span class="shopping-item-meta">${i.meals_needed > 1 ? `${i.meals_needed} meals` : "To buy"}</span>
        </div>
      </article>`
    )
    .join("");
}

function renderGroceryList(grocery) {
  const wrap = document.getElementById("meal-plan-grocery");
  const list = document.getElementById("meal-plan-grocery-list");
  const empty = document.getElementById("meal-plan-grocery-empty");
  const clearBtn = document.getElementById("plan-grocery-clear-checked");
  if (!wrap || !list) return;
  currentGrocery = grocery || null;
  const items = grocery?.items || [];
  wrap.hidden = false;
  if (!items.length) {
    list.innerHTML = "";
    if (empty) empty.hidden = false;
    if (clearBtn) clearBtn.hidden = true;
    syncFridgeShoppingPanel(grocery);
    return;
  }
  if (empty) empty.hidden = true;
  const checked = readGroceryChecked();
  list.innerHTML = items
    .map((item) => {
      const key = item.key || item.ingredient;
      const isChecked = checked.has(key);
      const sub =
        item.you_have_substitute?.length
          ? `<span class="grocery-sub">You have ${escapeHtml(item.you_have_substitute[0])} as a swap</span>`
          : item.substitutes?.length
            ? `<span class="grocery-sub">Try: ${item.substitutes.slice(0, 2).map((s) => escapeHtml(s)).join(", ")}</span>`
            : "";
      return `<label class="grocery-item${isChecked ? " is-checked" : ""}">
        <input type="checkbox" class="grocery-check" data-key="${escapeAttr(key)}" ${isChecked ? "checked" : ""} />
        <span class="grocery-item-body">
          <strong>${escapeHtml(item.ingredient)}</strong>
          <span class="grocery-meta">${item.meals_needed > 1 ? `Used in ${item.meals_needed} meals` : "To buy"}</span>
          ${sub}
        </span>
      </label>`;
    })
    .join("");
  if (clearBtn) clearBtn.hidden = ![...checked].some((k) => items.some((i) => (i.key || i.ingredient) === k));
  list.querySelectorAll(".grocery-check").forEach((input) => {
    input.addEventListener("change", () => {
      const next = readGroceryChecked();
      if (input.checked) next.add(input.dataset.key);
      else next.delete(input.dataset.key);
      writeGroceryChecked(next);
      input.closest(".grocery-item")?.classList.toggle("is-checked", input.checked);
      if (clearBtn) clearBtn.hidden = next.size === 0;
    });
  });
  syncFridgeShoppingPanel(grocery);
}

async function refreshGroceryFromPlan() {
  if (!currentMealPlan) return;
  const have = currentMealPlan.ingredients_used?.length
    ? currentMealPlan.ingredients_used
    : planIngredientsList();
  const body = { plan: currentMealPlan, have };
  if (userId) body.user_id = userId;
  try {
    const grocery = await api("/api/grocery-list", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (currentMealPlan) currentMealPlan.grocery = grocery;
    persistMealPlanSession(currentMealPlan);
    renderGroceryList(grocery);
    const n = grocery.count || grocery.items?.length || 0;
    planStatus(n ? `Grocery list updated — ${n} item${n === 1 ? "" : "s"} to buy.` : "Grocery list clear — you have what you need.");
  } catch (err) {
    planStatus(err.message || "Could not build grocery list.", true);
  }
}

function dayMeals(day) {
  if (Array.isArray(day?.meals) && day.meals.length) return day.meals;
  if (day?.meal) return [day.meal];
  return [];
}

function findPlanMeal(dayNum, slot) {
  const day = currentMealPlan?.days?.find((d) => d.day === Number(dayNum));
  return dayMeals(day).find((m) => m.slot === slot) || null;
}

function renderMealPlanSlot(dayNum, meal) {
  const slot = meal?.slot || "dinner";
  const label = meal?.label || slot;
  const recipe = meal?.recipe;
  if (!recipe) {
    return `<div class="meal-plan-slot-row meal-plan-slot-row--empty" data-day="${dayNum}" data-slot="${escapeAttr(slot)}">
      <div class="meal-plan-slot-head">
        <span class="meal-plan-slot">${escapeHtml(label)}</span>
        <button type="button" class="btn ghost plan-swap-btn" data-day="${dayNum}" data-slot="${escapeAttr(slot)}">Find meal</button>
      </div>
      <p class="meal-plan-slot-empty">No recipe yet</p>
    </div>`;
  }
  const missing = (recipe.missing_ingredients || []).slice(0, 3);
  const img =
    recipe.image ||
    "https://www.themealdb.com/images/media/meals/ssrrrs1503664277.jpg";
  return `<div class="meal-plan-slot-row" data-day="${dayNum}" data-slot="${escapeAttr(slot)}">
    <div class="meal-plan-slot-head">
      <span class="meal-plan-slot">${escapeHtml(label)}</span>
    </div>
    <div class="meal-plan-recipe">
      <img src="${escapeAttr(img)}" alt="" loading="lazy" onerror="this.onerror=null;this.src='https://www.themealdb.com/images/media/meals/ssrrrs1503664277.jpg'" />
      <div class="meal-plan-recipe-body">
        <h3>${escapeHtml(recipe.name || "Recipe")}</h3>
        <p class="meal-plan-meta">${escapeHtml(recipe.cuisine || "Various")} · ${recipe.time_min ?? "?"} min${recipe.calories ? ` · ${recipe.calories} kcal` : ""}${recipe.protein != null ? ` · P ${Number(recipe.protein).toFixed(0)}g` : ""}</p>
        ${
          missing.length
            ? `<p class="meal-plan-missing">Need: ${missing.map((m) => escapeHtml(m)).join(", ")}</p>`
            : ""
        }
      </div>
    </div>
    <div class="meal-plan-day-actions">
      <button type="button" class="btn ghost plan-swap-btn" data-day="${dayNum}" data-slot="${escapeAttr(slot)}">Swap</button>
      <button type="button" class="btn ghost plan-cook-btn" data-day="${dayNum}" data-slot="${escapeAttr(slot)}">Cook</button>
      <button type="button" class="btn ghost plan-open-match-btn" data-day="${dayNum}" data-slot="${escapeAttr(slot)}">Match</button>
    </div>
  </div>`;
}

function renderMealPlan(plan, opts = {}) {
  const host = document.getElementById("meal-plan-results");
  if (!host) return;
  currentMealPlan = plan;
  persistMealPlanSession(plan);
  updateMealPlanActionVisibility();
  if (plan?.grocery) renderGroceryList(plan.grocery);
  else if (opts.refreshGrocery !== false && plan?.days?.length) refreshGroceryFromPlan();
  else if (!plan?.days?.length) {
    const wrap = document.getElementById("meal-plan-grocery");
    if (wrap) wrap.hidden = true;
  }
  if (!plan?.days?.length) {
    host.innerHTML = `<p class="meal-plan-empty">Generate a plan to see breakfast, lunch, dinner, and snacks for each day.</p>`;
    return;
  }
  host.innerHTML = plan.days
    .map((day) => {
      const meals = dayMeals(day);
      return `<article class="meal-plan-day" data-day="${day.day}">
        <div class="meal-plan-day-head">
          <strong>${escapeHtml(day.label || `Day ${day.day}`)}</strong>
          <span class="meal-plan-day-count">${meals.filter((m) => m.recipe).length}/${meals.length || 4} meals</span>
        </div>
        <div class="meal-plan-slots">
          ${meals.map((meal) => renderMealPlanSlot(day.day, meal)).join("")}
        </div>
      </article>`;
    })
    .join("");

  host.querySelectorAll(".plan-swap-btn").forEach((btn) => {
    btn.addEventListener("click", () => swapMealPlanDay(Number(btn.dataset.day), btn.dataset.slot || "dinner"));
  });
  host.querySelectorAll(".plan-cook-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const meal = findPlanMeal(btn.dataset.day, btn.dataset.slot);
      if (meal?.recipe) cookRecipe(meal.recipe);
    });
  });
  host.querySelectorAll(".plan-open-match-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const meal = findPlanMeal(btn.dataset.day, btn.dataset.slot);
      const recipe = meal?.recipe;
      const fromPlan = currentMealPlan?.ingredients_used || planIngredientsList();
      const matched = recipe?.matched_ingredients || [];
      const seed = [...new Set([...(matched.length ? matched : fromPlan)])];
      if (seed.length) setIngredientsValue(seed);
      showPanel("matcher", { scrollTo: "match-ingredient-card", focus: "ingredient-add" });
    });
  });
}

async function loadPlanIngredientsFromFridge() {
  const statusTarget = document.getElementById("meal-plan-status");
  if (!requireLogin("load fridge ingredients")) return;
  if (!mongoAvailable) {
    setStatus(statusTarget, "Connect MongoDB to load fridge ingredients.", true);
    return;
  }
  try {
    const data = await api(`/api/pantry?user_id=${encodeURIComponent(userId)}`);
    const names = (data.items || []).map((item) => item.ingredient).filter(Boolean);
    if (!names.length) {
      planStatus("Your fridge is empty. Add items in the Fridge tab first.", true);
      return;
    }
    const el = document.getElementById("plan-ingredients");
    if (el) el.value = names.join(", ");
    planStatus(`Loaded ${names.length} ingredient${names.length === 1 ? "" : "s"} from your fridge.`);
  } catch (err) {
    planStatus(err.message, true);
  }
}

async function generateMealPlan() {
  const ingredients = planIngredientsList();
  const filters = collectPlanFilters();
  const body = {
    days: mealPlanDays,
    ingredients,
    ...filters,
  };
  if (userId) body.user_id = userId;
  if (!ingredients.length && !userId) {
    planStatus("Add ingredients or sign in and load from fridge.", true);
    return;
  }
  const genBtn = document.getElementById("plan-generate");
  if (genBtn) {
    genBtn.disabled = true;
    genBtn.textContent = "Generating…";
  }
  planStatus("Building your meal plan and grocery list…");
  try {
    const plan = await api("/api/meal-plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (plan.ingredients_used?.length) {
      const el = document.getElementById("plan-ingredients");
      if (el && !el.value.trim()) el.value = plan.ingredients_used.join(", ");
    }
    renderMealPlan(plan);
    const filled = plan.meals_filled || plan.days?.reduce((n, d) => n + dayMeals(d).filter((m) => m.recipe).length, 0) || 0;
    const groceryCount = plan.grocery?.count ?? plan.grocery?.items?.length ?? 0;
    planStatus(
      `Plan ready — ${plan.days?.length || 0} day${(plan.days?.length || 0) === 1 ? "" : "s"}, ${filled} meals` +
        (groceryCount ? `, ${groceryCount} grocery item${groceryCount === 1 ? "" : "s"}` : "") +
        (plan.preferences_applied ? " · personalized" : "") +
        "."
    );
    const banner = document.getElementById("plan-pref-banner");
    if (banner) {
      if (plan.preferences_applied) {
        banner.hidden = false;
        banner.textContent = "Meals ranked using your cuisines, favorites, cook history, and allergies.";
      } else {
        banner.hidden = true;
      }
    }
  } catch (err) {
    planStatus(err.message || "Could not generate meal plan.", true);
  } finally {
    if (genBtn) {
      genBtn.disabled = false;
      genBtn.textContent = "Generate plan";
    }
  }
}

async function swapMealPlanDay(dayNum, slot = "dinner") {
  if (!currentMealPlan) return;
  const ingredients = currentMealPlan.ingredients_used?.length
    ? currentMealPlan.ingredients_used
    : planIngredientsList();
  const exclude_ids = (currentMealPlan.days || [])
    .flatMap((d) => dayMeals(d).map((m) => m.recipe?.id || m.recipe?.name))
    .filter(Boolean)
    .map(String);
  const body = {
    day: dayNum,
    slot,
    ingredients,
    exclude_ids,
    ...(currentMealPlan.filters || collectPlanFilters()),
  };
  if (userId) body.user_id = userId;
  planStatus(`Swapping ${slot} on day ${dayNum}…`);
  try {
    const result = await api("/api/meal-plan/swap", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const days = (currentMealPlan.days || []).map((d) => {
      if (d.day !== result.day) return d;
      const meals = dayMeals(d).map((m) =>
        m.slot === (result.slot || slot) ? result.meal || m : m
      );
      const hasSlot = meals.some((m) => m.slot === (result.slot || slot));
      if (!hasSlot && result.meal) meals.push(result.meal);
      return {
        ...d,
        meals,
        meal: meals.find((m) => m.slot === "dinner") || meals[0] || null,
      };
    });
    renderMealPlan({ ...currentMealPlan, days, grocery: null }, { refreshGrocery: false });
    await refreshGroceryFromPlan();
    planStatus(`Day ${dayNum} ${slot} updated.`);
  } catch (err) {
    planStatus(err.message || "Could not swap meal.", true);
  }
}

async function saveMealPlan() {
  if (!currentMealPlan) return;
  if (!requireLogin("save meal plans")) return;
  if (!mongoAvailable) {
    planStatus("Connect MongoDB to save meal plans.", true);
    return;
  }
  try {
    const data = await api("/api/meal-plan/saved", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, plan: currentMealPlan }),
    });
    if (data.plan) renderMealPlan(data.plan);
    planStatus("Meal plan saved.");
  } catch (err) {
    planStatus(err.message || "Could not save plan.", true);
  }
}

async function deleteMealPlan() {
  if (!currentMealPlan?.days?.length) return;
  const ok = await askConfirm("This clears the plan and grocery list.", {
    title: "Delete meal plan?",
    okLabel: "Delete plan",
  });
  if (!ok) return;
  const btn = document.getElementById("plan-delete");
  if (btn) btn.disabled = true;
  try {
    if (userId && mongoAvailable) {
      await api(`/api/meal-plan/saved?user_id=${encodeURIComponent(userId)}`, { method: "DELETE" });
    }
    currentMealPlan = null;
    currentGrocery = null;
    persistMealPlanSession(null);
    writeGroceryChecked(new Set());
    renderMealPlan({ days: [] }, { refreshGrocery: false });
    const groceryWrap = document.getElementById("meal-plan-grocery");
    if (groceryWrap) groceryWrap.hidden = true;
    syncFridgeShoppingPanel(null);
    updateMealPlanActionVisibility();
    planStatus("");
  } catch (err) {
    planStatus(err.message || "Could not delete plan.", true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function loadMealPlanPanel() {
  updateMealPlanActionVisibility();
  if (currentMealPlan?.days?.length) {
    renderMealPlan(currentMealPlan);
    return;
  }
  const cached = readMealPlanSession();
  if (cached?.days?.length) {
    renderMealPlan(cached);
    return;
  }
  if (userId && mongoAvailable) {
    try {
      const data = await api(`/api/meal-plan/saved?user_id=${encodeURIComponent(userId)}`);
      if (data.plan?.days?.length) {
        renderMealPlan(data.plan);
        planStatus("Loaded your saved meal plan.");
        return;
      }
    } catch {
      /* ignore */
    }
  }
  const host = document.getElementById("meal-plan-results");
  if (host && !host.innerHTML.trim()) {
    host.innerHTML = `<p class="meal-plan-empty">Generate a plan to see breakfast, lunch, dinner, and snacks for each day.</p>`;
  }
}

function initMealPlan() {
  document.querySelectorAll(".meal-plan-day-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      mealPlanDays = Number(btn.dataset.days) || 3;
      document.querySelectorAll(".meal-plan-day-btn").forEach((b) => {
        b.classList.toggle("active", b === btn);
      });
    });
  });
  document.getElementById("plan-load-fridge")?.addEventListener("click", loadPlanIngredientsFromFridge);
  document.getElementById("plan-generate")?.addEventListener("click", generateMealPlan);
  document.getElementById("plan-regenerate")?.addEventListener("click", generateMealPlan);
  document.getElementById("plan-save")?.addEventListener("click", saveMealPlan);
  document.getElementById("plan-delete")?.addEventListener("click", deleteMealPlan);
  document.getElementById("plan-grocery-refresh")?.addEventListener("click", refreshGroceryFromPlan);
  document.getElementById("plan-grocery-clear-checked")?.addEventListener("click", () => {
    writeGroceryChecked(new Set());
    if (currentGrocery) renderGroceryList(currentGrocery);
  });
}

/* —— Restaurant discovery (maps) —— */
let discoverMap = null;
let discoverMarkers = null;
let discoverCenterMarker = null;
let discoverPlaces = [];
let discoverCenter = null;
let discoverSelectedId = null;
let discoverGeocodeTimer = null;
let discoverMapReady = false;
let discoverSearchSeq = 0;

function discoverStatus(message, isError = false) {
  setStatus(document.getElementById("discover-status"), message, isError);
}

function ensureDiscoverMap() {
  const el = document.getElementById("discover-map");
  if (!el) return null;
  if (typeof L === "undefined") {
    el.innerHTML = `<div class="discover-map-fallback"><p>Map library failed to load.</p><p class="muted">Check your internet connection, then refresh.</p></div>`;
    return null;
  }
  if (discoverMap) {
    setTimeout(() => discoverMap.invalidateSize(), 80);
    return discoverMap;
  }
  discoverMap = L.map(el, { scrollWheelZoom: true, zoomControl: true }).setView([24.8607, 67.0011], 12);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(discoverMap);
  discoverMarkers = L.layerGroup().addTo(discoverMap);
  discoverMapReady = true;
  setTimeout(() => discoverMap.invalidateSize(), 120);
  return discoverMap;
}

function setDiscoverCenter(lat, lng, label = "") {
  discoverCenter = { lat, lng, label: label || discoverCenter?.label || "" };
  const map = ensureDiscoverMap();
  if (!map) return;
  if (discoverCenterMarker) {
    discoverCenterMarker.setLatLng([lat, lng]);
  } else {
    discoverCenterMarker = L.circleMarker([lat, lng], {
      radius: 8,
      color: "#e2b04a",
      fillColor: "#e2b04a",
      fillOpacity: 0.85,
      weight: 2,
    }).addTo(map);
  }
  discoverCenterMarker.bindPopup(escapeHtml(label || "Search center")).openPopup();
}

function renderDiscoverMarkers(places) {
  const map = ensureDiscoverMap();
  if (!map || !discoverMarkers) return;
  discoverMarkers.clearLayers();
  places.forEach((place) => {
    if (place.lat == null || place.lng == null) return;
    const marker = L.circleMarker([place.lat, place.lng], {
      radius: 7,
      color: "#4cae6e",
      fillColor: place.place_id === discoverSelectedId ? "#e2b04a" : "#6bc98a",
      fillOpacity: 0.9,
      weight: 2,
    });
    marker.bindTooltip(place.name || "Restaurant");
    marker.on("click", () => openDiscoverDetail(place.place_id));
    discoverMarkers.addLayer(marker);
  });
}

function placeChips(place) {
  const chips = [];
  if (place.cuisine) chips.push(escapeHtml(place.cuisine));
  if (place.rating != null) chips.push(`★ ${Number(place.rating).toFixed(1)}`);
  if (place.halal) chips.push("Halal");
  if (place.haram) chips.push("Haram");
  if (place.vegetarian) chips.push("Vegetarian");
  if (place.delivery) chips.push("Delivery");
  if (place.distance_km != null) chips.push(`${Number(place.distance_km).toFixed(1)} km`);
  return chips.map((c) => `<span class="discover-chip">${c}</span>`).join("");
}

function renderDiscoverResults(places) {
  const host = document.getElementById("discover-results");
  if (!host) return;
  if (!places.length) {
    host.innerHTML = `<p class="discover-empty muted">No restaurants match these filters. Try a wider radius or clear diet filters.</p>`;
    return;
  }
  host.innerHTML = places
    .map((p) => {
      const active = p.place_id === discoverSelectedId ? " is-active" : "";
      const saved = p.saved ? " is-saved" : "";
      return `<button type="button" class="discover-card${active}${saved}" data-place-id="${escapeAttr(p.place_id)}">
        <strong>${escapeHtml(p.name || "Restaurant")}</strong>
        <span class="discover-card-meta">${escapeHtml(p.address || p.area || "Address unknown")}</span>
        <span class="discover-chips">${placeChips(p)}</span>
      </button>`;
    })
    .join("");
}

function findDiscoverPlace(placeId) {
  return discoverPlaces.find((p) => p.place_id === placeId) || null;
}

function setDiscoverDetailOpen(open) {
  const side = document.getElementById("discover-side");
  const drawer = document.getElementById("discover-detail");
  if (side) side.classList.toggle("is-detail-open", !!open);
  if (drawer) drawer.hidden = !open;
}

function renderDiscoverDetailContent(place) {
  const drawer = document.getElementById("discover-detail");
  if (!drawer || !place) return;

  const reviews = (place.reviews || [])
    .map(
      (r) =>
        `<li><strong>${escapeHtml(r.author || "Note")}</strong> — ${escapeHtml(r.text || "")}</li>`
    )
    .join("");
  const menuHref = place.menu_url || place.website || "";
  const reviewsHref = place.reviews_url || place.google_maps_url || "";
  const directionsHref = place.directions_url || "";
  const mapsHref = place.google_maps_url || place.maps_url || "";
  const amenity = (place.amenity || "restaurant").replace(/_/g, " ");
  const facts = [];
  if (place.cuisine) facts.push(["Cuisine", place.cuisine]);
  if (place.rating != null) facts.push(["Rating", `${Number(place.rating).toFixed(1)} / 5`]);
  if (place.distance_km != null) facts.push(["Distance", `${Number(place.distance_km).toFixed(1)} km away`]);
  if (place.halal) facts.push(["Diet", "Halal"]);
  else if (place.haram) facts.push(["Diet", "Haram / non-halal"]);
  if (place.vegetarian) facts.push(["Options", "Vegetarian / vegan"]);
  if (place.delivery) facts.push(["Service", "Delivery available"]);
  if (place.phone) facts.push(["Phone", place.phone]);
  if (place.opening_hours) facts.push(["Hours", place.opening_hours]);
  if (place.address || place.area) facts.push(["Address", place.address || place.area]);
  if (place.website) facts.push(["Website", place.website]);
  if (place.lat != null && place.lng != null) {
    facts.push(["Coordinates", `${Number(place.lat).toFixed(5)}, ${Number(place.lng).toFixed(5)}`]);
  }

  const factsHtml = facts
    .map(([label, value]) => {
      const isPhone = label === "Phone";
      const isWeb = label === "Website";
      let valHtml = escapeHtml(String(value));
      if (isPhone) valHtml = `<a href="tel:${escapeAttr(value)}">${escapeHtml(value)}</a>`;
      if (isWeb) valHtml = `<a href="${escapeAttr(value)}" target="_blank" rel="noopener">${escapeHtml(value)}</a>`;
      return `<div class="discover-fact"><dt>${escapeHtml(label)}</dt><dd>${valHtml}</dd></div>`;
    })
    .join("");

  drawer.innerHTML = `
    <div class="discover-detail-head">
      <button type="button" class="btn ghost discover-detail-back" id="discover-detail-close">← Back to list</button>
      <p class="discover-detail-eyebrow">${escapeHtml(amenity)}</p>
      <h3>${escapeHtml(place.name || "Restaurant")}</h3>
      <p class="muted">${escapeHtml(place.address || place.area || "Address not listed")}</p>
      <div class="discover-chips">${placeChips(place)}</div>
    </div>
    <div class="discover-detail-actions">
      <button type="button" class="btn ${place.saved ? "ghost" : "primary"}" id="discover-save-btn" data-place-id="${escapeAttr(place.place_id)}">
        ${place.saved ? "Saved ★" : "Save favorite"}
      </button>
      ${directionsHref ? `<a class="btn ghost" href="${escapeAttr(directionsHref)}" target="_blank" rel="noopener">Directions</a>` : ""}
      ${menuHref ? `<a class="btn ghost" href="${escapeAttr(menuHref)}" target="_blank" rel="noopener">Menu / site</a>` : ""}
      ${reviewsHref ? `<a class="btn ghost" href="${escapeAttr(reviewsHref)}" target="_blank" rel="noopener">Reviews</a>` : ""}
      ${mapsHref ? `<a class="btn ghost" href="${escapeAttr(mapsHref)}" target="_blank" rel="noopener">Open map</a>` : ""}
    </div>
    <h4 class="discover-detail-section">About this place</h4>
    <dl class="discover-facts">${factsHtml || `<p class="muted">Basic map listing — open Reviews for more info.</p>`}</dl>
    ${place.reviews_note ? `<p class="muted discover-reviews-note">${escapeHtml(place.reviews_note)}</p>` : ""}
    ${reviews ? `<h4 class="discover-detail-section">Notes</h4><ul class="discover-reviews">${reviews}</ul>` : ""}
  `;
}

async function openDiscoverDetail(placeId) {
  const drawer = document.getElementById("discover-detail");
  if (!drawer || !placeId) return;
  discoverSelectedId = placeId;
  renderDiscoverResults(discoverPlaces);
  renderDiscoverMarkers(discoverPlaces);

  let place = findDiscoverPlace(placeId);
  setDiscoverDetailOpen(true);
  if (place) {
    renderDiscoverDetailContent(place);
  } else {
    drawer.innerHTML = `<p class="muted">Loading details…</p>`;
  }
  drawer.scrollTop = 0;

  try {
    const params = new URLSearchParams();
    if (discoverCenter) {
      params.set("lat", String(discoverCenter.lat));
      params.set("lng", String(discoverCenter.lng));
    }
    if (userId) params.set("user_id", userId);
    const data = await api(`/api/places/${encodeURIComponent(placeId)}?${params}`);
    if (discoverSelectedId !== placeId) return;
    place = { ...(place || {}), ...(data.place || {}) };
    const idx = discoverPlaces.findIndex((p) => p.place_id === placeId);
    if (idx >= 0) discoverPlaces[idx] = { ...discoverPlaces[idx], ...place };
    renderDiscoverDetailContent(place);
  } catch {
    if (!place) {
      drawer.innerHTML = `<p class="muted">Could not load this place.</p>
        <button type="button" class="btn ghost" id="discover-detail-close">← Back to list</button>`;
    }
  }

  if (discoverMap && place?.lat != null && place?.lng != null) {
    discoverMap.panTo([place.lat, place.lng], { animate: true });
  }
}

async function toggleDiscoverSave(placeId) {
  if (!requireLogin("save restaurants")) return;
  const place = findDiscoverPlace(placeId);
  if (!place) return;
  const btn = document.getElementById("discover-save-btn");
  if (btn) btn.disabled = true;
  try {
    const data = await api("/api/saved-restaurants", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: userId,
        restaurant_name: place.name || place.restaurant_name,
        area: place.area || "",
        place_id: place.place_id,
        address: place.address || "",
        lat: place.lat,
        lng: place.lng,
        rating: place.rating ?? null,
        price_level: place.price_level ?? null,
        cuisine: place.cuisine || "",
        website: place.website || place.menu_url || "",
        maps_url: place.maps_url || place.google_maps_url || "",
        directions_url: place.directions_url || "",
        halal: !!place.halal,
        vegetarian: !!place.vegetarian,
        delivery: !!place.delivery,
      }),
    });
    const saved = !!data.saved;
    discoverPlaces = discoverPlaces.map((p) =>
      p.place_id === placeId ? { ...p, saved } : p
    );
    if (saved) discoverStatus("Saved to favorites.");
    else discoverStatus("");
    await openDiscoverDetail(placeId);
    renderDiscoverResults(discoverPlaces);
  } catch (err) {
    discoverStatus(err.message, true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function resolveDiscoverLocation(query) {
  const geo = await api(`/api/places/geocode?q=${encodeURIComponent(query)}&limit=5`);
  const hits = geo.results || [];
  if (!hits.length) return null;
  return hits[0];
}

async function runDiscoverSearch(opts = {}) {
  const seq = ++discoverSearchSeq;
  ensureDiscoverMap();
  const locationInput = document.getElementById("discover-location");
  const query = (locationInput?.value || "").trim();
  const hasCoords = opts.lat != null && opts.lng != null && Number.isFinite(Number(opts.lat)) && Number.isFinite(Number(opts.lng));

  let lat;
  let lng;
  let label;

  if (hasCoords) {
    // Near me / suggestion / filter refresh — trust provided coords
    lat = Number(opts.lat);
    lng = Number(opts.lng);
    label = opts.label || discoverCenter?.label || query || `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
  } else if (query) {
    // Always re-geocode typed text (fixes stale center from previous search)
    discoverStatus("Looking up location…");
    try {
      const hit = await resolveDiscoverLocation(query);
      if (!hit) {
        discoverStatus("Location not found. Try a city, area, or paste lat,lng.", true);
        return;
      }
      lat = hit.lat;
      lng = hit.lng;
      label = hit.label || query;
      if (locationInput) locationInput.value = label;
    } catch (err) {
      discoverStatus(err.message, true);
      return;
    }
  } else if (discoverCenter) {
    lat = discoverCenter.lat;
    lng = discoverCenter.lng;
    label = discoverCenter.label;
  } else {
    discoverStatus("Enter a location or tap Near me.", true);
    return;
  }

  setDiscoverCenter(lat, lng, label);

  const minRating = document.getElementById("discover-rating")?.value || "";
  const diet = document.getElementById("discover-diet")?.value || "";
  const params = new URLSearchParams({
    lat: String(lat),
    lng: String(lng),
    radius: "5000",
    limit: "20",
    min_results: "10",
  });
  if (minRating) params.set("min_rating", minRating);
  if (diet === "halal") params.set("halal", "true");
  if (diet === "haram") params.set("haram", "true");
  if (userId) params.set("user_id", userId);

  discoverStatus("Finding nearby restaurants…");
  try {
    const data = await api(`/api/places/nearby?${params}`);
    if (seq !== discoverSearchSeq) return;
    discoverPlaces = data.places || [];
    discoverSelectedId = null;
    setDiscoverDetailOpen(false);
    const map = ensureDiscoverMap();
    const usedRadius = Number(discoverPlaces[0]?.search_radius_m) || Number(data.radius_m) || 5000;
    if (map) {
      const rKm = usedRadius / 1000;
      const zoom = rKm <= 1.2 ? 15 : rKm <= 3 ? 14 : rKm <= 6 ? 13 : rKm <= 10 ? 12 : 11;
      map.setView([lat, lng], zoom);
    }
    renderDiscoverMarkers(discoverPlaces);
    renderDiscoverResults(discoverPlaces);
    const n = discoverPlaces.length;
    discoverStatus(n ? `Found ${n} place${n === 1 ? "" : "s"} nearby.` : "No restaurants in this area.");
  } catch (err) {
    if (seq !== discoverSearchSeq) return;
    discoverStatus(err.message || "Could not find restaurants. Try again.", true);
    showToast(err.message || "Restaurant search failed. Try again in a moment.", true, {
      rich: true,
      variant: "error",
      icon: "📍",
      title: "Discover unavailable",
      duration: 7000,
    });
  }
}

async function discoverUseMyLocation() {
  if (!navigator.geolocation) {
    discoverStatus("Geolocation is not supported in this browser.", true);
    return;
  }
  discoverStatus("Getting your location…");
  navigator.geolocation.getCurrentPosition(
    async (pos) => {
      const lat = pos.coords.latitude;
      const lng = pos.coords.longitude;
      let label = `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
      try {
        const rev = await api(`/api/places/reverse?lat=${lat}&lng=${lng}`);
        label = rev.result?.label || label;
      } catch {
        /* keep coords label */
      }
      const input = document.getElementById("discover-location");
      if (input) input.value = label;
      setDiscoverCenter(lat, lng, label);
      await runDiscoverSearch({ lat, lng, label });
    },
    (err) => {
      discoverStatus(err.message || "Could not get your location.", true);
    },
    { enableHighAccuracy: true, timeout: 12000 }
  );
}

async function discoverShowSuggestions(q) {
  const box = document.getElementById("discover-suggestions");
  if (!box) return;
  if (!q || q.trim().length < 2) {
    box.hidden = true;
    box.innerHTML = "";
    return;
  }
  try {
    const data = await api(`/api/places/geocode?q=${encodeURIComponent(q.trim())}&limit=5`);
    const results = data.results || [];
    if (!results.length) {
      box.hidden = true;
      return;
    }
    box.hidden = false;
    box.innerHTML = results
      .map(
        (r) =>
          `<button type="button" class="discover-suggestion" data-lat="${escapeAttr(r.lat)}" data-lng="${escapeAttr(r.lng)}" data-label="${escapeAttr(r.label)}">${escapeHtml(r.label)}</button>`
      )
      .join("");
  } catch {
    box.hidden = true;
  }
}

function loadRestaurantsPanel() {
  ensureDiscoverMap();
  const results = document.getElementById("discover-results");
  if (results && !discoverPlaces.length) {
    results.innerHTML = `<p class="discover-empty muted">Search a city or tap <strong>Near me</strong> to find restaurants on the map.</p>`;
  } else {
    renderDiscoverResults(discoverPlaces);
    renderDiscoverMarkers(discoverPlaces);
  }
}

function initRestaurants() {
  document.getElementById("discover-search")?.addEventListener("click", () => runDiscoverSearch());
  document.getElementById("discover-locate")?.addEventListener("click", () => discoverUseMyLocation());
  document.getElementById("discover-location")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      document.getElementById("discover-suggestions").hidden = true;
      runDiscoverSearch();
    }
  });
  document.getElementById("discover-location")?.addEventListener("input", (e) => {
    clearTimeout(discoverGeocodeTimer);
    discoverGeocodeTimer = setTimeout(() => discoverShowSuggestions(e.target.value), 320);
  });
  document.getElementById("discover-suggestions")?.addEventListener("click", (e) => {
    const btn = e.target.closest(".discover-suggestion");
    if (!btn) return;
    const lat = Number(btn.dataset.lat);
    const lng = Number(btn.dataset.lng);
    const label = btn.dataset.label || "";
    const input = document.getElementById("discover-location");
    if (input) input.value = label;
    document.getElementById("discover-suggestions").hidden = true;
    setDiscoverCenter(lat, lng, label);
    runDiscoverSearch({ lat, lng, label });
  });
  const refreshFromCenter = () => {
    if (!discoverCenter) return;
    runDiscoverSearch({
      lat: discoverCenter.lat,
      lng: discoverCenter.lng,
      label: discoverCenter.label,
    });
  };
  ["discover-rating", "discover-diet"].forEach((id) => {
    document.getElementById(id)?.addEventListener("change", refreshFromCenter);
  });
  document.getElementById("discover-results")?.addEventListener("click", (e) => {
    const card = e.target.closest(".discover-card");
    if (card?.dataset.placeId) openDiscoverDetail(card.dataset.placeId);
  });
  document.getElementById("discover-detail")?.addEventListener("click", (e) => {
    if (e.target.closest("#discover-detail-close")) {
      setDiscoverDetailOpen(false);
      discoverSelectedId = null;
      renderDiscoverResults(discoverPlaces);
      renderDiscoverMarkers(discoverPlaces);
      return;
    }
    const saveBtn = e.target.closest("#discover-save-btn");
    if (saveBtn?.dataset.placeId) toggleDiscoverSave(saveBtn.dataset.placeId);
  });
  document.addEventListener("click", (e) => {
    const box = document.getElementById("discover-suggestions");
    if (!box || box.hidden) return;
    if (!e.target.closest("#discover-suggestions") && !e.target.closest("#discover-location")) {
      box.hidden = true;
    }
  });
}

async function loadCuisineOptions() {
  const select = document.getElementById("filter-cuisine");
  if (!select) return;
  const existing = new Set([...select.options].map((opt) => opt.value).filter(Boolean));
  try {
    const data = await api("/api/cuisines");
    for (const cuisine of data.cuisines || []) {
      if (existing.has(cuisine)) continue;
      const option = document.createElement("option");
      option.value = cuisine;
      option.textContent = cuisine;
      select.appendChild(option);
      existing.add(cuisine);
    }
  } catch {
    /* static options already in HTML */
  }
}

function recipeMissingIngredients(recipe, userLeftovers) {
  const rows = recipeIngredientRows(recipe);
  const leftovers = userLeftovers.length ? userLeftovers : recipe.matched_ingredients || [];
  const missingFromRows = rows
    .map((row) => row.ingredient)
    .filter(
      (ing) =>
        !leftovers.some((l) => ingredientMatchesLeftover(l, ing)) &&
        !(recipe.matched_ingredients || []).some((m) => ingredientMatchesLeftover(m, ing))
    );
  return [...new Set([...(recipe.missing_ingredients || []), ...missingFromRows])];
}

function substitutionForIngredient(recipe, ingredient) {
  const list = recipe.substitutions || [];
  return (
    list.find((s) => ingredientMatchesLeftover(s.ingredient, ingredient)) ||
    list.find((s) => ingredientMatchesLeftover(ingredient, s.ingredient)) ||
    null
  );
}

function renderSubstitutionHint(sub) {
  if (!sub?.substitutes?.length) return "";
  const haveSet = new Set((sub.you_have || []).map((s) => s.toLowerCase()));
  const chips = sub.substitutes
    .map((alt) => {
      const owned = haveSet.has(String(alt).toLowerCase()) ||
        (sub.you_have || []).some((h) => ingredientMatchesLeftover(h, alt));
      return `<button type="button" class="sub-chip${owned ? " you-have" : ""}" data-add-sub="${escapeAttr(alt)}" title="${owned ? "You already have this — add to search" : "Add this substitute to your search"}">${escapeHtml(alt)}${owned ? " · have" : ""}</button>`;
    })
    .join("");
  return `<div class="sub-hint"><span class="sub-hint-label">Try instead</span><div class="sub-chips">${chips}</div></div>`;
}

function renderMissingIngredients(recipe, userLeftovers) {
  const missing = recipeMissingIngredients(recipe, userLeftovers);
  if (!missing.length) {
    return `<p class="missing-none">✓ You have all ingredients for this recipe</p>`;
  }
  return `<div class="missing-ingredients">
    <strong>Missing ingredients</strong>
    <ul class="missing-list missing-list--subs">
      ${missing
        .map((item) => {
          const sub = substitutionForIngredient(recipe, item);
          return `<li class="missing-item">
            <span class="missing-item-name"><span aria-hidden="true">${pantryItemIcon(item)}</span>${escapeHtml(item)}</span>
            ${renderSubstitutionHint(sub)}
          </li>`;
        })
        .join("")}
    </ul>
  </div>`;
}

function addSubstituteToSearch(name) {
  if (!name || !input) return;
  const next = mergeIngredients(input.value, [name]);
  input.value = next;
  renderIngredientPills();
  showToast(`Added substitute: ${name}`);
  input.focus();
}

function wireSubstitutionButtons(root = resultsEl) {
  root?.querySelectorAll("[data-add-sub]").forEach((btn) => {
    btn.addEventListener("click", () => addSubstituteToSearch(btn.dataset.addSub));
  });
}

function initMatchForm() {
  document.getElementById("ingredient-add-btn")?.addEventListener("click", addIngredientFromInput);
  document.getElementById("ingredient-add")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      addIngredientFromInput();
    }
  });
  document.getElementById("load-pantry-btn")?.addEventListener("click", loadFridgeFromPantry);
  loadCuisineOptions();
}

input.addEventListener("input", renderIngredientPills);
input.addEventListener("blur", renderIngredientPills);

function normalizeSpokenIngredients(transcript) {
  let text = transcript.toLowerCase().trim();
  text = text
    .replace(/\bi have\b/g, " ")
    .replace(/\bleftovers?\b/g, " ")
    .replace(/\bingredients?\b/g, " ")
    .replace(/\band\b/g, ",")
    .replace(/\bplus\b/g, ",")
    .replace(/[.]/g, ",")
    .replace(/\s+/g, " ")
    .trim();
  const parts = text
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => s.replace(/^(some|a|an|the|few|leftover)\s+/i, "").trim())
    .filter(Boolean);
  return [...new Set(parts)];
}

function mergeIngredients(existingRaw, spokenList) {
  const current = parseIngredients(existingRaw).map((s) => s.toLowerCase());
  const merged = parseIngredients(existingRaw);
  for (const item of spokenList) {
    if (!current.includes(item.toLowerCase())) {
      merged.push(item);
      current.push(item.toLowerCase());
    }
  }
  return merged.join(", ");
}

function syncIngredientsFromVoice(spokenList) {
  input.value = mergeIngredients(input.value, spokenList);
  renderIngredientPills();
}

function setVoiceUi(isListening, message = "", isError = false) {
  listening = isListening;
  if (voiceBtn) {
    voiceBtn.classList.toggle("listening", isListening);
    voiceBtn.setAttribute("aria-pressed", String(isListening));
  }
  if (!voiceHint) return;
  if (message) {
    voiceHint.hidden = false;
    voiceHint.textContent = message;
    voiceHint.classList.toggle("error", isError);
  } else if (!isListening) {
    voiceHint.hidden = true;
  }
}

function setupVoice() {
  if (!voiceBtn || !SpeechRecognition) return;
  recognition = new SpeechRecognition();
  recognition.lang = "en-US";
  recognition.interimResults = true;
  recognition.continuous = false;
  recognition.onstart = () => setVoiceUi(true, "Listening… say ingredients like tomato, egg, onion");
  recognition.onresult = (event) => {
    let interim = "";
    let finalText = "";
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const chunk = event.results[i][0].transcript;
      if (event.results[i].isFinal) finalText += chunk;
      else interim += chunk;
    }
    if (interim) setVoiceUi(true, `Hearing: ${interim}`);
    if (finalText) {
      const spoken = normalizeSpokenIngredients(finalText);
      if (spoken.length) {
        syncIngredientsFromVoice(spoken);
        setVoiceUi(false, `Added: ${spoken.join(", ")}`);
      } else setVoiceUi(false, "Didn’t catch any ingredients.", true);
    }
  };
  recognition.onerror = (event) => {
    setVoiceUi(
      false,
      event.error === "not-allowed" ? "Mic permission blocked." : `Voice error: ${event.error}`,
      true
    );
  };
  recognition.onend = () => {
    if (listening) setVoiceUi(false);
  };
  voiceBtn.addEventListener("click", () => {
    if (listening) {
      recognition.stop();
      setVoiceUi(false);
      return;
    }
    try {
      recognition.start();
    } catch {
      setVoiceUi(false, "Could not start microphone.", true);
    }
  });
}

function recipeSourceLabel(r) {
  if (r.generated) return "T5 generated";
  if (r.search_mode === "google") return "Google";
  if (r.search_mode === "dish_name") return "dish match";
  if (r.source_model === "themealdb") return "TheMealDB";
  return `semantic ${r.semantic_score ?? r.match_score}%`;
}

function matchSourceLabel(source) {
  const map = {
    dish_name: "dish name",
    "dish+leftovers": "dish + leftovers",
    google: "Google",
    "hybrid+google": "T5 + catalog + Google",
    hybrid: "catalog + T5",
    "t5-recipe-generation": "T5 Chef Transformer",
    catalog: "catalog",
  };
  return map[source] || source || "hybrid";
}

function youtubeSearchUrl(name) {
  return `https://www.youtube.com/results?search_query=${encodeURIComponent(`${name || "recipe"} recipe`)}`;
}

function recipeVideoUrl(recipe) {
  const url = String(recipe.video_url || recipe.source_url || "").trim();
  if (/youtube\.com|youtu\.be/i.test(url)) return url;
  return youtubeSearchUrl(recipe.name);
}

function recipePageUrl(recipe) {
  const url = String(recipe.source_url || recipe.video_url || "").trim();
  if (!url || /youtube\.com|youtu\.be/i.test(url)) return "";
  if (recipe.search_mode === "google") return url;
  return "";
}

function renderRecipeVideoLinks(recipe) {
  const videoUrl = recipeVideoUrl(recipe);
  const pageUrl = recipePageUrl(recipe);
  const isDirectVideo = /youtube\.com\/watch|youtu\.be\//i.test(videoUrl);
  const recipeJson = escapeAttr(JSON.stringify(recipe));
  const saved = favoriteRecipeIds.has(recipe.id);
  return `
    <div class="recipe-video-row">
      <a class="btn ghost recipe-video-btn" href="${escapeAttr(videoUrl)}" target="_blank" rel="noopener">
        <span class="recipe-video-icon" aria-hidden="true">▶</span>
        ${isDirectVideo ? "Watch on YouTube" : "Find recipe video"}
      </a>
      ${pageUrl ? `<a class="btn ghost recipe-page-btn" href="${escapeAttr(pageUrl)}" target="_blank" rel="noopener">View full recipe</a>` : ""}
      <button type="button" class="btn ghost fav-btn${saved ? " is-favorited" : ""}" data-recipe="${recipeJson}" aria-pressed="${saved}">
        ${saved ? "♥ Saved" : "♡ Add to favorites"}
      </button>
      <button type="button" class="btn ghost cook-btn" data-recipe="${recipeJson}" title="Add to Recipes — I cooked this" aria-label="I cooked this">
        <span class="cook-btn-icon" aria-hidden="true">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 11h18v2a7 7 0 0 1-7 7h-4a7 7 0 0 1-7-7v-2z"/><path d="M7 11V7a2 2 0 0 1 2-2h0"/><path d="M17 11V7a2 2 0 0 0-2-2h0"/><path d="M12 5V3"/></svg>
        </span>
        I cooked this
      </button>
    </div>`;
}

async function loadFavoriteIds() {
  favoriteRecipeIds = new Set();
  if (!userId || !mongoAvailable) return;
  try {
    const data = await api(`/api/favorites?user_id=${encodeURIComponent(userId)}`);
    for (const item of data.favorites || []) {
      const id = item.recipe_id || item.recipe?.id;
      if (id) favoriteRecipeIds.add(id);
    }
  } catch {
    favoriteRecipeIds = new Set();
  }
}

function updateFavoriteButton(btn, favorited) {
  btn.classList.toggle("is-favorited", favorited);
  btn.setAttribute("aria-pressed", String(favorited));
  btn.textContent = favorited ? "♥ Saved" : "♡ Add to favorites";
}

function renderSummary(_data) {
  summaryEl.hidden = true;
  summaryEl.innerHTML = "";
}

function renderNutritionBar(r) {
  const cal = r.calories ?? r.nutrition?.calories;
  const protein = r.protein ?? r.nutrition?.protein_g;
  const carbs = r.carbs ?? r.nutrition?.carbs_g;
  const fat = r.fat ?? r.nutrition?.fat_g;
  if (cal == null && protein == null && carbs == null && fat == null) return "";
  const p = Number(protein) || 0;
  const c = Number(carbs) || 0;
  const f = Number(fat) || 0;
  const kcal = cal != null ? Math.round(Number(cal)) : null;
  const total = Math.max(p + c + f, 0.1);
  const pPct = Math.round((p / total) * 100);
  const cPct = Math.round((c / total) * 100);
  const fPct = Math.max(0, 100 - pPct - cPct);
  return `<div class="nutrition-panel" title="Per serving estimate">
    <div class="nutrition-panel-top">
      <span class="nutrition-panel-label">Nutrition</span>
      ${kcal != null ? `<span class="nutrition-kcal"><em>${kcal}</em> kcal</span>` : ""}
    </div>
    <div class="nutrition-stat-row" role="list">
      <div class="nutrition-stat nutrition-stat--protein" role="listitem">
        <span class="nutrition-stat-value">${p.toFixed(0)}<small>g</small></span>
        <span class="nutrition-stat-name">Protein</span>
      </div>
      <div class="nutrition-stat nutrition-stat--carbs" role="listitem">
        <span class="nutrition-stat-value">${c.toFixed(0)}<small>g</small></span>
        <span class="nutrition-stat-name">Carbs</span>
      </div>
      <div class="nutrition-stat nutrition-stat--fat" role="listitem">
        <span class="nutrition-stat-value">${f.toFixed(0)}<small>g</small></span>
        <span class="nutrition-stat-name">Fat</span>
      </div>
    </div>
    <div class="nutrition-track" aria-hidden="true">
      <span class="nutrition-seg nutrition-seg--protein" style="width:${pPct}%"></span>
      <span class="nutrition-seg nutrition-seg--carbs" style="width:${cPct}%"></span>
      <span class="nutrition-seg nutrition-seg--fat" style="width:${fPct}%"></span>
    </div>
    <p class="nutrition-panel-note">Per serving</p>
  </div>`;
}

function renderNutritionDashboard(recipes) {
  const el = document.getElementById("nutrition-dashboard");
  if (!el) return;
  if (!recipes?.length) {
    el.hidden = true;
    el.innerHTML = "";
    return;
  }
  const rows = recipes.filter((r) => r.calories != null || r.protein != null);
  if (!rows.length) {
    el.hidden = true;
    el.innerHTML = "";
    return;
  }
  const n = rows.length;
  const avg = (key, alt) => {
    const vals = rows.map((r) => Number(r[key] ?? r.nutrition?.[alt]) || 0);
    return vals.reduce((a, b) => a + b, 0) / n;
  };
  const cal = Math.round(avg("calories", "calories"));
  const protein = Math.round(avg("protein", "protein_g"));
  const carbs = Math.round(avg("carbs", "carbs_g"));
  const fat = Math.round(avg("fat", "fat_g"));
  const total = Math.max(protein + carbs + fat, 0.1);
  const pPct = Math.round((protein / total) * 100);
  const cPct = Math.round((carbs / total) * 100);
  const fPct = Math.max(0, 100 - pPct - cPct);
  el.hidden = false;
  el.innerHTML = `
    <div class="nutrition-dashboard-inner">
      <div class="nutrition-dashboard-head">
        <div>
          <h3>Nutrition</h3>
          <p class="muted">Average per serving · ${n} recipe${n === 1 ? "" : "s"}</p>
        </div>
        <div class="nutrition-dashboard-kcal">
          <em>${cal}</em>
          <span>kcal</span>
        </div>
      </div>
      <div class="nutrition-dashboard-grid">
        <div class="nutrition-dash-card nutrition-dash-card--protein">
          <span class="nutrition-dash-value">${protein}<small>g</small></span>
          <span class="nutrition-dash-name">Protein</span>
        </div>
        <div class="nutrition-dash-card nutrition-dash-card--carbs">
          <span class="nutrition-dash-value">${carbs}<small>g</small></span>
          <span class="nutrition-dash-name">Carbs</span>
        </div>
        <div class="nutrition-dash-card nutrition-dash-card--fat">
          <span class="nutrition-dash-value">${fat}<small>g</small></span>
          <span class="nutrition-dash-name">Fat</span>
        </div>
      </div>
      <div class="nutrition-track nutrition-track--lg" aria-hidden="true">
        <span class="nutrition-seg nutrition-seg--protein" style="width:${pPct}%"></span>
        <span class="nutrition-seg nutrition-seg--carbs" style="width:${cPct}%"></span>
        <span class="nutrition-seg nutrition-seg--fat" style="width:${fPct}%"></span>
      </div>
    </div>`;
}

function renderRecipes(recipes) {
  lastRecipes = recipes;
  const userLeftovers = lastSearchQuery.length ? lastSearchQuery : [];
  renderNutritionDashboard(recipes);
  resultsEl.innerHTML = recipes
    .map((r, i) => {
      const steps =
        Array.isArray(r.steps) && r.steps.length
          ? r.steps
          : String(r.instructions || "").split(/(?<=\.)\s+/).filter(Boolean);
      const ingredientPanel = buildIngredientPanel(r, userLeftovers, { compact: true });
      return `
        <article class="recipe" style="animation-delay:${i * 0.06}s">
          <img src="${escapeAttr(r.image)}" alt="${escapeAttr(r.name)}" loading="lazy" onerror="this.onerror=null;this.src='https://www.themealdb.com/images/media/meals/ssrrrs1503664277.jpg'" />
          <div class="recipe-body">
            <h3>${escapeHtml(r.name)}</h3>
            <div class="meta">
              <span>${escapeHtml(r.cuisine || "Various")}</span>
              <span>${r.time_min ?? "?"} min</span>
              ${r.difficulty ? `<span>${escapeHtml(difficultyLabel(r.difficulty))}</span>` : ""}
              <span class="score">${r.match_score}% fit · ${recipeSourceLabel(r)}</span>
            </div>
            ${renderNutritionBar(r)}
            <div class="tags">
              ${r.search_mode === "dish_name" ? `<span class="tag pref">Dish match</span>` : ""}
              ${r.search_mode === "google" ? `<span class="tag pref">Google</span>` : ""}
              ${r.generated ? `<span class="tag pref">AI Chef</span>` : ""}
              ${r.diet === "vegan" ? `<span class="tag pref">Vegan</span>` : ""}
              ${r.diet === "non-vegan" ? `<span class="tag pref">Non-vegan</span>` : ""}
              ${r.halal ? `<span class="tag pref">${escapeHtml(r.halal)}</span>` : ""}
              ${r.goal ? `<span class="tag pref">${escapeHtml(goalLabel(r.goal))}</span>` : ""}
            </div>
            ${renderRecipeVideoLinks(r)}
            ${renderMissingIngredients(r, userLeftovers)}
            ${ingredientPanel}
            <h4 class="steps-heading">Recipe steps</h4>
            <ol class="steps">${steps.map((s) => `<li>${escapeHtml(s)}</li>`).join("")}</ol>
          </div>
        </article>`;
    })
    .join("");

  resultsEl.querySelectorAll(".ingredient-view-all").forEach((btn) => {
    btn.addEventListener("click", () => openRecipeIngredientsDialog(JSON.parse(btn.dataset.recipe)));
  });
  resultsEl.querySelectorAll(".fav-btn").forEach((btn) => {
    btn.addEventListener("click", () => toggleFavorite(JSON.parse(btn.dataset.recipe), btn));
  });
  resultsEl.querySelectorAll(".cook-btn").forEach((btn) => {
    btn.addEventListener("click", () => cookRecipe(JSON.parse(btn.dataset.recipe), btn));
  });
  wireSubstitutionButtons(resultsEl);
}

async function cookRecipe(recipe, btn = null) {
  if (!requireLogin("log cooked meals")) return;
  if (!mongoAvailable) {
    setStatus(statusEl, "Start MongoDB to log cooked meals.", true);
    return;
  }
  if (btn) {
    btn.disabled = true;
    btn.classList.add("is-logging");
  }
  try {
    const data = await api("/api/cook", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, recipe }),
    });
    let msg = `Logged ${recipe.name}! +${data.points_earned} pts · streak ${data.streak}`;
    if (data.new_badges?.length) msg += ` · Badges: ${data.new_badges.join(", ")}`;
    setStatus(statusEl, msg);
    showToast(msg, false, {
      rich: true,
      variant: "success",
      title: "Added to Recipes",
      duration: 3200,
    });
    if (btn) {
      btn.classList.remove("is-logging");
      btn.classList.add("is-cooked");
      btn.innerHTML = `<span class="cook-btn-icon" aria-hidden="true">✓</span> Cooked`;
      btn.title = "Logged in Recipes";
      btn.disabled = false;
    }
  } catch (err) {
    setStatus(statusEl, err.message, true);
    showToast(err.message, true);
    if (btn) {
      btn.disabled = false;
      btn.classList.remove("is-logging");
    }
  }
}

async function toggleFavorite(recipe, btn) {
  if (!requireLogin("save favorites")) return;
  if (!mongoAvailable) {
    setStatus(statusEl, "Start MongoDB to save favorites.", true);
    return;
  }
  try {
    const data = await api("/api/favorites", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, recipe }),
    });
    if (data.favorited) favoriteRecipeIds.add(recipe.id);
    else favoriteRecipeIds.delete(recipe.id);
    updateFavoriteButton(btn, data.favorited);
    setStatus(statusEl, data.favorited ? "Added to favorites!" : "");
  } catch (err) {
    setStatus(statusEl, err.message, true);
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const ingredients = parseIngredients(input.value);
  if (!ingredients.length) {
    setStatus(statusEl, "Add leftovers or a dish name.", true);
    return;
  }
  submitBtn.disabled = true;
  submitBtn.textContent = "Searching…";
  setStatus(statusEl, "Searching catalog, Google & web in parallel…");
  summaryEl.hidden = true;
  resultsEl.innerHTML = "";
  resultsEl.classList.add("loading");
  try {
    const filters = collectMatchFilters();
    const res = await fetch("/api/match", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ingredients,
        top_k: 5,
        ...filters,
        user_id: userId,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Match failed");
    lastSearchQuery = data.query || ingredients;
    if (!data.count) {
      setStatus(statusEl, "No recipes found. Try another dish or more leftovers.", true);
      return;
    }
    setStatus(
      statusEl,
      `${data.count} recipes for: ${data.query.join(", ")} · via ${matchSourceLabel(data.source)}${formatActiveFilters(data.filters || filters)}${data.preferences?.active ? " · personalized" : ""}`
    );
    showPrefBanner("match-pref-banner", data.preferences);
    renderSummary(data);
    await loadFavoriteIds();
    renderRecipes(data.recipes);
    const missing = [
      ...new Set(
        (data.recipes || []).flatMap((r) => recipeMissingIngredients(r, lastSearchQuery))
      ),
    ];
    if (missing.length) {
      pendingShoppingMissing = missing;
      loadShoppingList(missing);
    }
  } catch (err) {
    setStatus(statusEl, err.message || "Something went wrong.", true);
  } finally {
    resultsEl.classList.remove("loading");
    submitBtn.disabled = false;
    submitBtn.textContent = "Find recipes";
  }
});

function openDeleteAccountDialog() {
  const dialog = document.getElementById("delete-account-dialog");
  const error = document.getElementById("delete-account-error");
  const password = document.getElementById("delete-account-password");
  const passwordWrap = document.getElementById("delete-account-password-wrap");
  const confirmWrap = document.getElementById("delete-account-confirm-wrap");
  const confirmInput = document.getElementById("delete-account-confirm-text");
  const phrase = document.getElementById("delete-account-phrase");
  const warning = document.getElementById("delete-account-warning");
  const oauthOnly = session && session.has_password === false;
  if (password) password.value = "";
  if (confirmInput) confirmInput.value = "";
  if (error) error.hidden = true;
  if (passwordWrap) passwordWrap.hidden = !!oauthOnly;
  if (confirmWrap) confirmWrap.hidden = !oauthOnly;
  if (phrase && session?.username) phrase.textContent = `delete ${session.username}`;
  if (warning) {
    warning.textContent = oauthOnly
      ? `This permanently removes your profile and data. Type "delete ${session.username}" below to confirm.`
      : "This permanently removes your profile, pantry, favorites, posts, and cooking history. Type your password below to confirm — this cannot be undone.";
  }
  dialog?.showModal();
}

async function handleDeleteAccount(e) {
  e.preventDefault();
  const error = document.getElementById("delete-account-error");
  const password = document.getElementById("delete-account-password")?.value || "";
  const confirmText = document.getElementById("delete-account-confirm-text")?.value || "";
  if (!userId) return;
  const oauthOnly = session && session.has_password === false;
  try {
    await api("/api/auth/account", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(
        oauthOnly
          ? { user_id: userId, confirm_text: confirmText }
          : { user_id: userId, password }
      ),
    });
    document.getElementById("delete-account-dialog")?.close();
    clearSession();
    updateAuthUi();
    showPanel("matcher");
    loadPantry();
    loadProfile();
    loadAdmin();
    setStatus(document.getElementById("profile-status"), "Account deleted successfully.");
  } catch (err) {
    if (error) {
      error.hidden = false;
      error.textContent = err.message;
    }
  }
}

async function loadShoppingList(missing) {
  const pantryStatus = document.getElementById("pantry-status");
  if (!missing?.length) return;
  try {
    const body = { missing };
    if (userId) body.user_id = userId;
    const data = await api("/api/grocery-list", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    syncFridgeShoppingPanel(data);
  } catch (err) {
    setStatus(pantryStatus, err.message, true);
  }
}

function showToast(message, isError = false, opts = {}) {
  const host = document.getElementById("toast-host");
  if (!host || (!message && !opts.title)) return;
  const variant = opts.variant || (isError ? "error" : "info");
  const toast = document.createElement("div");
  toast.className = `toast toast--${variant}${opts.rich ? " toast--rich" : ""}`;
  toast.setAttribute("role", "status");
  if (opts.rich || opts.title) {
    const icon = opts.icon || (variant === "warn" ? "🍽️" : variant === "error" ? "⚠️" : variant === "success" ? "✓" : "ℹ️");
    toast.innerHTML = `
      <span class="toast-icon" aria-hidden="true">${icon}</span>
      <span class="toast-body">
        ${opts.title ? `<strong class="toast-title">${escapeHtml(opts.title)}</strong>` : ""}
        ${message ? `<span class="toast-text">${escapeHtml(message)}</span>` : ""}
      </span>`;
  } else {
    toast.textContent = message;
  }
  host.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add("show"));
  const ms = opts.duration || (variant === "warn" ? 6500 : 5000);
  setTimeout(() => {
    toast.classList.remove("show");
    setTimeout(() => toast.remove(), 300);
  }, ms);
}

/** In-app confirm (replaces browser confirm()). Returns true if confirmed. */
function askConfirm(message, opts = {}) {
  const dialog = document.getElementById("confirm-dialog");
  const form = document.getElementById("confirm-dialog-form");
  const titleEl = document.getElementById("confirm-dialog-title");
  const msgEl = document.getElementById("confirm-dialog-message");
  const okBtn = document.getElementById("confirm-dialog-ok");
  const cancelBtn = document.getElementById("confirm-dialog-cancel");
  if (!dialog || !form || !msgEl || !okBtn || !cancelBtn) {
    return Promise.resolve(window.confirm(message));
  }
  if (titleEl) titleEl.textContent = opts.title || "Confirm";
  msgEl.textContent = message;
  okBtn.textContent = opts.okLabel || "Confirm";
  okBtn.className = `btn ${opts.danger === false ? "primary" : "danger"}`;
  cancelBtn.textContent = opts.cancelLabel || "Cancel";

  return new Promise((resolve) => {
    const finish = (ok) => {
      form.removeEventListener("submit", onSubmit);
      cancelBtn.removeEventListener("click", onCancel);
      dialog.removeEventListener("cancel", onEscape);
      if (dialog.open) dialog.close();
      resolve(ok);
    };
    const onSubmit = (e) => {
      e.preventDefault();
      finish(true);
    };
    const onCancel = () => finish(false);
    const onEscape = (e) => {
      e.preventDefault();
      finish(false);
    };
    form.addEventListener("submit", onSubmit);
    cancelBtn.addEventListener("click", onCancel);
    dialog.addEventListener("cancel", onEscape);
    if (typeof dialog.showModal === "function") dialog.showModal();
    else finish(window.confirm(message));
    okBtn.focus();
  });
}

function showScanNotFoodNotice(data = {}) {
  const title = "Not a food ingredient";
  const detail =
    data.hint ||
    "That photo doesn’t look like groceries or leftovers. Try scanning produce, packaged food, or a meal plate.";
  showToast(detail, false, {
    rich: true,
    variant: "warn",
    icon: "🥗",
    title,
    duration: 7000,
  });
  const host = document.getElementById("pantry-scan-results");
  if (!host) return;
  host.hidden = false;
  host.innerHTML = `
    <div class="pantry-scan-empty" role="status">
      <div class="pantry-scan-empty-icon" aria-hidden="true">🥗</div>
      <h4>Not a food ingredient</h4>
      <p>We couldn’t find edible items in this photo.</p>
      <ul class="pantry-scan-empty-tips">
        <li>Use a clear close-up of food</li>
        <li>Good lighting helps a lot</li>
        <li>Or add items manually below</li>
      </ul>
      <button type="button" class="btn ghost" id="pantry-scan-retry">Try another photo</button>
    </div>`;
  document.getElementById("pantry-scan-retry")?.addEventListener("click", () => {
    clearFoodScan();
    document.getElementById("pantry-scan-input")?.click();
  });
}

function fridgeNotifyEnabled() {
  return localStorage.getItem(FRIDGE_NOTIFY_KEY) === "true";
}

function setFridgeNotifyEnabled(on) {
  localStorage.setItem(FRIDGE_NOTIFY_KEY, on ? "true" : "false");
  updateFridgeNotifyBar();
}

function notifiedFridgeKeys() {
  try {
    return JSON.parse(localStorage.getItem(FRIDGE_NOTIFIED_KEY) || "[]");
  } catch {
    return [];
  }
}

function markFridgeNotified(alerts) {
  const keys = notifiedFridgeKeys();
  for (const alert of alerts) {
    const key = `${alert.item_id || alert.ingredient}:${alert.expiry_date}`;
    if (!keys.includes(key)) keys.push(key);
  }
  localStorage.setItem(FRIDGE_NOTIFIED_KEY, JSON.stringify(keys.slice(-50)));
}

function newFridgeAlerts(alerts) {
  const seen = new Set(notifiedFridgeKeys());
  return alerts.filter((a) => !seen.has(`${a.item_id || a.ingredient}:${a.expiry_date}`));
}

async function requestFridgeNotifications() {
  if (!("Notification" in window)) {
    showToast("Browser notifications are not supported here.", true);
    return false;
  }
  const permission = await Notification.requestPermission();
  const ok = permission === "granted";
  setFridgeNotifyEnabled(ok);
  if (ok) {
    showToast("Fridge expiry alerts enabled.");
    startFridgeAlertPolling();
  } else if (permission === "denied") {
    showToast("Notifications blocked — enable them in browser settings.", true);
  }
  return ok;
}

function pushFridgeNotifications(alerts) {
  if (!fridgeNotifyEnabled() || !alerts.length || Notification.permission !== "granted") return;
  const fresh = newFridgeAlerts(alerts);
  if (!fresh.length) return;
  const first = fresh[0];
  const more = fresh.length - 1;
  const body =
    more > 0
      ? `${first.message} (+${more} more item${more === 1 ? "" : "s"})`
      : first.message;
  try {
    const note = new Notification("Petugram · Fridge alert", { body, tag: "petugram-fridge" });
    note.onclick = () => {
      window.focus();
      showPanel("pantry", { scrollTo: "pantry-alerts-card" });
      note.close();
    };
  } catch {
    /* ignore */
  }
  markFridgeNotified(fresh);
}

function updateFridgeAlertBadge(count = 0) {
  const btn = document.getElementById("fridge-alert-btn");
  const label = document.getElementById("fridge-alert-count");
  if (!btn || !label) return;
  if (userId && mongoAvailable) {
    btn.hidden = false;
    const n = Number(count) || 0;
    label.textContent = String(n);
    label.hidden = n <= 0;
    btn.classList.toggle("has-alerts", n > 0);
    const tip =
      n > 0
        ? `${n} fridge item${n === 1 ? "" : "s"} expiring soon — open fridge`
        : "Fridge — check expiry alerts";
    btn.title = tip;
    btn.setAttribute("aria-label", tip);
  } else {
    btn.hidden = true;
    label.hidden = true;
    label.textContent = "0";
    btn.classList.remove("has-alerts");
  }
}

function updateFridgeNotifyBar() {
  const bar = document.getElementById("fridge-notify-bar");
  const text = document.getElementById("fridge-notify-text");
  const btn = document.getElementById("fridge-notify-enable");
  if (!bar || !text || !btn) return;
  if (!("Notification" in window)) {
    bar.hidden = true;
    return;
  }
  if (Notification.permission === "granted" && fridgeNotifyEnabled()) {
    bar.hidden = true;
    return;
  }
  bar.hidden = false;
  text.textContent =
    Notification.permission === "denied"
      ? "Notifications are blocked in your browser. Enable them in site settings to get expiry alerts."
      : "Turn on notifications to get reminded before fridge items expire.";
  btn.textContent = Notification.permission === "denied" ? "How to enable" : "Enable alerts";
}

async function handleFridgeAlerts(alerts) {
  updateFridgeAlertBadge(alerts.length);
  updateFridgeNotifyBar();
  if (!alerts.length) return;
  const fresh = newFridgeAlerts(alerts);
  if (fresh.length) {
    const names = fresh.slice(0, 2).map((a) => a.ingredient).join(", ");
    const suffix = fresh.length > 2 ? ` +${fresh.length - 2} more` : "";
    showToast(`Expiring soon: ${names}${suffix}`);
    pushFridgeNotifications(fresh);
  }
}

async function pollFridgeAlerts() {
  if (!userId || !mongoAvailable) return;
  try {
    const data = await api(`/api/expiry-alerts?user_id=${encodeURIComponent(userId)}&days=3`);
    await handleFridgeAlerts(data.alerts || []);
  } catch {
    /* ignore */
  }
}

function startFridgeAlertPolling() {
  if (fridgeNotifyTimer) clearInterval(fridgeNotifyTimer);
  if (!userId || !mongoAvailable) return;
  pollFridgeAlerts();
  fridgeNotifyTimer = setInterval(pollFridgeAlerts, 5 * 60 * 1000);
}

function scanStatus(message, isError = false) {
  setStatus(document.getElementById("pantry-scan-status"), message, isError);
}

function renderScanDetections(detections, caption, meta = {}) {
  const host = document.getElementById("pantry-scan-results");
  if (!host) return;
  if (!detections?.length) {
    showScanNotFoodNotice(meta);
    return;
  }
  host.hidden = false;
  host.innerHTML = `
    <p class="pantry-scan-confirm-hint">Select items to add (uses the expiry date above):</p>
    <div class="pantry-scan-list">
      ${detections
        .map(
          (d, i) => `<label class="pantry-scan-item">
            <input type="checkbox" name="scan-ing" value="${escapeAttr(d.ingredient)}" checked data-idx="${i}" />
            <span class="pantry-scan-item-icon" aria-hidden="true">${pantryItemIcon(d.ingredient)}</span>
            <span class="pantry-scan-item-name">${escapeHtml(d.ingredient)}</span>
            <span class="pantry-scan-item-conf">${Math.round((d.confidence || 0) * 100)}%</span>
          </label>`
        )
        .join("")}
    </div>
    <div class="pantry-scan-confirm-row">
      <button type="button" class="btn primary" id="pantry-scan-add">Add selected to fridge</button>
      <button type="button" class="btn ghost" id="pantry-scan-clear">Clear</button>
    </div>`;
  document.getElementById("pantry-scan-add")?.addEventListener("click", confirmScanToFridge);
  document.getElementById("pantry-scan-clear")?.addEventListener("click", clearFoodScan);
}

function clearFoodScan() {
  const input = document.getElementById("pantry-scan-input");
  const previewWrap = document.getElementById("pantry-scan-preview-wrap");
  const preview = document.getElementById("pantry-scan-preview");
  const host = document.getElementById("pantry-scan-results");
  stopBarcodeCamera();
  if (input) input.value = "";
  if (previewWrap) previewWrap.hidden = true;
  if (preview) {
    preview.hidden = false;
    preview.removeAttribute("src");
  }
  if (host) {
    host.hidden = true;
    host.innerHTML = "";
  }
  scanStatus("");
}

let pantryScanMode = "photo";
let barcodeCameraStream = null;
let barcodeScanTimer = null;

function setPantryScanMode(mode) {
  pantryScanMode = mode === "receipt" || mode === "barcode" ? mode : "photo";
  document.querySelectorAll(".pantry-scan-mode").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.scanMode === pantryScanMode);
  });
  const photoTools = document.getElementById("pantry-scan-photo-tools");
  const barcodeTools = document.getElementById("pantry-scan-barcode-tools");
  const label = document.getElementById("pantry-scan-upload-label");
  if (photoTools) photoTools.hidden = pantryScanMode === "barcode";
  if (barcodeTools) barcodeTools.hidden = pantryScanMode !== "barcode";
  if (label) {
    label.textContent = pantryScanMode === "receipt" ? "Take / upload receipt" : "Take / upload photo";
  }
  stopBarcodeCamera();
  if (pantryScanMode !== "barcode") {
    const video = document.getElementById("pantry-barcode-video");
    if (video) video.hidden = true;
  }
}

function stopBarcodeCamera() {
  if (barcodeScanTimer) {
    clearInterval(barcodeScanTimer);
    barcodeScanTimer = null;
  }
  if (barcodeCameraStream) {
    barcodeCameraStream.getTracks().forEach((t) => t.stop());
    barcodeCameraStream = null;
  }
  const video = document.getElementById("pantry-barcode-video");
  if (video) {
    video.srcObject = null;
    video.hidden = true;
  }
}

async function runFoodScan(file) {
  const pantryStatus = document.getElementById("pantry-status");
  if (!requireLogin("scan food into your fridge")) return;
  if (!mongoAvailable) {
    scanStatus("Connect MongoDB to use the food scanner.", true);
    return;
  }
  if (!file) return;

  const previewWrap = document.getElementById("pantry-scan-preview-wrap");
  const preview = document.getElementById("pantry-scan-preview");
  const video = document.getElementById("pantry-barcode-video");
  if (video) video.hidden = true;
  if (preview && previewWrap) {
    preview.src = URL.createObjectURL(file);
    preview.hidden = false;
    previewWrap.hidden = false;
  }

  const mode = pantryScanMode === "receipt" ? "receipt" : "photo";
  scanStatus(mode === "receipt" ? "Reading receipt with AI…" : "Scanning ingredients with AI…");
  const fd = new FormData();
  fd.append("user_id", userId);
  fd.append("file", file);
  fd.append("mode", mode);
  try {
    const res = await fetch("/api/pantry/scan", { method: "POST", body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data.detail;
      const message = Array.isArray(detail)
        ? detail.map((d) => d.msg || String(d)).join(", ")
        : detail || data.message || `Scan failed (${res.status})`;
      throw new Error(message);
    }
    const detections = data.detections || [];
    renderScanDetections(detections, data.caption || "", data);
    if (!detections.length || data.is_food === false) {
      scanStatus(data.hint || "");
    } else {
      scanStatus("");
      const n = detections.length;
      showToast(
        mode === "receipt"
          ? `Found ${n} item${n === 1 ? "" : "s"} — select what to add.`
          : `Found ${n} ingredient${n === 1 ? "" : "s"} — select what to add.`,
        false,
        {
          rich: true,
          variant: "success",
          icon: "✨",
          title: mode === "receipt" ? "Receipt scanned" : "Ingredients found",
          duration: 3500,
        }
      );
    }
    setStatus(pantryStatus, "");
  } catch (err) {
    scanStatus("");
    showToast(err.message || "Scan failed. Try another photo.", true, {
      rich: true,
      variant: "error",
      icon: "⚠️",
      title: "Scan failed",
      duration: 6500,
    });
    document.getElementById("pantry-scan-results").hidden = true;
  }
}

async function lookupBarcode(code) {
  if (!requireLogin("scan barcodes")) return;
  if (!mongoAvailable) {
    scanStatus("Connect MongoDB to look up barcodes.", true);
    return;
  }
  const barcode = String(code || "").replace(/\D/g, "");
  if (barcode.length < 8) {
    scanStatus("Enter a valid barcode (8–14 digits).", true);
    return;
  }
  scanStatus("Looking up product…");
  try {
    const data = await api("/api/pantry/scan/barcode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, barcode }),
    });
    stopBarcodeCamera();
    renderScanDetections(data.detections || [], data.caption || "", data);
    scanStatus(data.message || "Product found.");
    showToast(data.message || "Product found.", false, {
      rich: true,
      variant: "success",
      icon: "📦",
      title: "Barcode match",
      duration: 3500,
    });
  } catch (err) {
    scanStatus(err.message || "Product not found.", true);
  }
}

async function startBarcodeCamera() {
  if (!requireLogin("scan barcodes")) return;
  if (!("BarcodeDetector" in window)) {
    showToast("Camera barcode scan isn’t supported here — enter the number instead.", true);
    document.getElementById("pantry-barcode-input")?.focus();
    return;
  }
  stopBarcodeCamera();
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" } },
      audio: false,
    });
    barcodeCameraStream = stream;
    const previewWrap = document.getElementById("pantry-scan-preview-wrap");
    const preview = document.getElementById("pantry-scan-preview");
    const video = document.getElementById("pantry-barcode-video");
    if (preview) preview.hidden = true;
    if (previewWrap) previewWrap.hidden = false;
    if (video) {
      video.hidden = false;
      video.srcObject = stream;
      await video.play();
    }
    const detector = new BarcodeDetector({
      formats: ["ean_13", "ean_8", "upc_a", "upc_e", "code_128", "qr_code"],
    });
    scanStatus("Point the camera at a barcode…");
    barcodeScanTimer = setInterval(async () => {
      if (!video || video.readyState < 2) return;
      try {
        const codes = await detector.detect(video);
        const value = codes?.[0]?.rawValue;
        if (value) {
          stopBarcodeCamera();
          const input = document.getElementById("pantry-barcode-input");
          if (input) input.value = String(value).replace(/\D/g, "");
          await lookupBarcode(value);
        }
      } catch {
        /* keep scanning */
      }
    }, 700);
  } catch (err) {
    scanStatus(err.message || "Could not open camera.", true);
  }
}

async function confirmScanToFridge() {
  const pantryStatus = document.getElementById("pantry-status");
  if (!requireLogin("add scanned items")) return;
  const checked = [...document.querySelectorAll('input[name="scan-ing"]:checked')].map((el) => el.value);
  if (!checked.length) {
    scanStatus("Select at least one ingredient.", true);
    return;
  }
  initPantryFormDefaults();
  const expiry_date = document.getElementById("pantry-expiry")?.value || defaultExpiryDate(7);
  const qty = document.getElementById("pantry-qty")?.value?.trim() || "1";
  const btn = document.getElementById("pantry-scan-add");
  if (btn) btn.disabled = true;
  scanStatus("Adding to fridge…");
  try {
    const data = await api("/api/pantry/scan/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, ingredients: checked, expiry_date, qty }),
    });
    scanStatus(`Added ${data.count} item${data.count === 1 ? "" : "s"} to your fridge.`);
    setStatus(pantryStatus, `Scanner added ${data.count} ingredient${data.count === 1 ? "" : "s"}.`);
    clearFoodScan();
    await loadPantry();
  } catch (err) {
    scanStatus(err.message, true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function initFoodScanner() {
  document.querySelectorAll(".pantry-scan-mode").forEach((btn) => {
    btn.addEventListener("click", () => setPantryScanMode(btn.dataset.scanMode || "photo"));
  });
  document.getElementById("pantry-scan-input")?.addEventListener("change", (e) => {
    const file = e.target.files?.[0];
    if (file) runFoodScan(file);
  });
  document.getElementById("pantry-barcode-lookup")?.addEventListener("click", () => {
    lookupBarcode(document.getElementById("pantry-barcode-input")?.value || "");
  });
  document.getElementById("pantry-barcode-input")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      lookupBarcode(e.target.value || "");
    }
  });
  document.getElementById("pantry-barcode-camera")?.addEventListener("click", startBarcodeCamera);
  setPantryScanMode("photo");
}

/* —— Surplus food sharing —— */
let surplusView = "near";
let surplusCoords = null;
let surplusPantryItemId = null;

function surplusStatus(message, isError = false) {
  setStatus(document.getElementById("surplus-status"), message, isError);
}

function openSurplusCompose(prefill = {}) {
  showPanel("surplus");
  const guest = document.getElementById("surplus-guest");
  const shell = document.getElementById("surplus-shell");
  if (!userId) {
    if (guest) guest.hidden = false;
    if (shell) shell.hidden = true;
    return;
  }
  if (guest) guest.hidden = true;
  if (shell) shell.hidden = false;
  const ing = document.getElementById("surplus-ingredient");
  const qty = document.getElementById("surplus-qty");
  const exp = document.getElementById("surplus-expiry");
  if (ing) ing.value = prefill.ingredient || "";
  if (qty) qty.value = prefill.qty || "1";
  if (exp && prefill.expiry_date) exp.value = prefill.expiry_date;
  surplusPantryItemId = prefill.pantry_item_id || null;
  ing?.focus();
}

function renderSurplusList(offers) {
  const list = document.getElementById("surplus-list");
  if (!list) return;
  if (!offers.length) {
    list.innerHTML = `<div class="surplus-empty">
      <span aria-hidden="true">🥗</span>
      <p>${surplusView === "mine" ? "You haven’t posted any offers yet." : "No surplus offers nearby yet."}</p>
      <p class="muted">${surplusView === "mine" ? "Share something from your fridge before it spoils." : "Be the first — offer leftovers, or widen location."}</p>
    </div>`;
    return;
  }
  list.innerHTML = offers
    .map((o) => {
      const mine = userId && o.user_id === userId;
      const dist =
        o.distance_km != null ? `${o.distance_km} km` : o.area ? escapeHtml(o.area) : "Nearby";
      const expiry = o.expiry_date ? `Best before ${escapeHtml(o.expiry_date)}` : "";
      const status = o.status === "claimed" ? `<span class="surplus-badge">Claimed</span>` : "";
      const actions = mine
        ? `<button type="button" class="btn ghost surplus-close" data-id="${escapeAttr(o.offer_id)}">Close</button>`
        : o.status === "open"
          ? `<button type="button" class="btn primary surplus-claim" data-id="${escapeAttr(o.offer_id)}">Claim</button>`
          : "";
      return `<article class="surplus-card" data-id="${escapeAttr(o.offer_id)}">
        <div class="surplus-card-body">
          <div class="surplus-card-top">
            <strong>${escapeHtml(o.title || o.ingredient)}</strong>
            ${status}
          </div>
          <p class="surplus-card-meta">Qty ${escapeHtml(o.qty || "1")} · ${dist}${expiry ? ` · ${expiry}` : ""}</p>
          <p class="surplus-card-owner">${escapeHtml(o.display_name || o.username || "Neighbor")}</p>
          ${o.note ? `<p class="surplus-card-note">${escapeHtml(o.note)}</p>` : ""}
        </div>
        <div class="surplus-card-actions">${actions}</div>
      </article>`;
    })
    .join("");
  list.querySelectorAll(".surplus-claim").forEach((btn) => {
    btn.addEventListener("click", () => claimSurplusOffer(btn.dataset.id, btn));
  });
  list.querySelectorAll(".surplus-close").forEach((btn) => {
    btn.addEventListener("click", () => closeSurplusOffer(btn.dataset.id, btn));
  });
}

async function loadSurplusOffers() {
  if (!mongoAvailable) {
    surplusStatus("Connect MongoDB to browse surplus food.", true);
    return;
  }
  surplusStatus("Loading offers…");
  try {
    const params = new URLSearchParams();
    if (userId) params.set("viewer_id", userId);
    if (surplusView === "mine") params.set("mine", "true");
    if (surplusCoords) {
      params.set("lat", String(surplusCoords.lat));
      params.set("lng", String(surplusCoords.lng));
      params.set("radius_km", "25");
    }
    const data = await api(`/api/surplus?${params}`);
    renderSurplusList(data.offers || []);
    surplusStatus(
      surplusView === "mine"
        ? `${(data.offers || []).length} of your offer(s)`
        : surplusCoords
          ? `${(data.offers || []).length} offer(s) near you`
          : `${(data.offers || []).length} open offer(s) — tap Use my location to sort by distance`
    );
  } catch (err) {
    surplusStatus(err.message || "Could not load offers.", true);
  }
}

async function loadSurplusPanel() {
  const guest = document.getElementById("surplus-guest");
  const shell = document.getElementById("surplus-shell");
  if (!userId) {
    if (guest) guest.hidden = false;
    if (shell) shell.hidden = true;
    return;
  }
  if (guest) guest.hidden = true;
  if (shell) shell.hidden = false;
  document.querySelectorAll(".surplus-tab").forEach((t) => {
    t.classList.toggle("is-active", t.dataset.surplusView === surplusView);
  });
  await loadSurplusOffers();
}

async function createSurplusOffer(e) {
  e?.preventDefault?.();
  if (!requireLogin("share surplus food")) return;
  if (!mongoAvailable) {
    surplusStatus("Connect MongoDB to post offers.", true);
    return;
  }
  const ingredient = document.getElementById("surplus-ingredient")?.value.trim();
  if (!ingredient) {
    surplusStatus("Add what you’re sharing.", true);
    return;
  }
  const body = {
    user_id: userId,
    ingredient,
    qty: document.getElementById("surplus-qty")?.value.trim() || "1",
    expiry_date: document.getElementById("surplus-expiry")?.value || null,
    note: document.getElementById("surplus-note")?.value.trim() || "",
    area: document.getElementById("surplus-area")?.value.trim() || "",
    pantry_item_id: surplusPantryItemId,
  };
  if (surplusCoords) {
    body.lat = surplusCoords.lat;
    body.lng = surplusCoords.lng;
  }
  try {
    await api("/api/surplus", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    document.getElementById("surplus-form")?.reset();
    surplusPantryItemId = null;
    surplusView = "mine";
    document.querySelectorAll(".surplus-tab").forEach((t) => {
      t.classList.toggle("is-active", t.dataset.surplusView === "mine");
    });
    showToast("Surplus offer posted.");
    await loadSurplusOffers();
  } catch (err) {
    surplusStatus(err.message || "Could not post offer.", true);
  }
}

async function claimSurplusOffer(offerId, btn) {
  if (!requireLogin("claim surplus food")) return;
  if (btn) btn.disabled = true;
  try {
    const data = await api(`/api/surplus/${encodeURIComponent(offerId)}/claim`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId }),
    });
    showToast("Claimed — check Inbox to arrange pickup.");
    if (data.conversation_id) {
      showPanel("messages");
    } else {
      await loadSurplusOffers();
    }
  } catch (err) {
    showToast(err.message || "Could not claim offer.", true);
    if (btn) btn.disabled = false;
  }
}

async function closeSurplusOffer(offerId, btn) {
  if (!requireLogin("close offers")) return;
  const ok = await askConfirm("People nearby won’t see this offer anymore.", {
    title: "Close this offer?",
    okLabel: "Close offer",
  });
  if (!ok) return;
  if (btn) btn.disabled = true;
  try {
    await api(`/api/surplus/${encodeURIComponent(offerId)}?user_id=${encodeURIComponent(userId)}`, {
      method: "DELETE",
    });
    await loadSurplusOffers();
  } catch (err) {
    showToast(err.message || "Could not close offer.", true);
    if (btn) btn.disabled = false;
  }
}

function locateForSurplus() {
  if (!navigator.geolocation) {
    surplusStatus("Geolocation is not supported in this browser.", true);
    return;
  }
  surplusStatus("Getting your location…");
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      surplusCoords = { lat: pos.coords.latitude, lng: pos.coords.longitude };
      surplusStatus("Location set — sorting nearby offers.");
      loadSurplusOffers();
    },
    (err) => {
      surplusStatus(err.message || "Could not get location.", true);
    },
    { enableHighAccuracy: false, timeout: 12000 }
  );
}

function initSurplus() {
  document.getElementById("surplus-login-btn")?.addEventListener("click", () => openAuthDialog("login"));
  document.getElementById("surplus-form")?.addEventListener("submit", createSurplusOffer);
  document.getElementById("surplus-locate")?.addEventListener("click", locateForSurplus);
  document.querySelectorAll(".surplus-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      surplusView = tab.dataset.surplusView === "mine" ? "mine" : "near";
      document.querySelectorAll(".surplus-tab").forEach((t) => {
        t.classList.toggle("is-active", t === tab);
      });
      loadSurplusOffers();
    });
  });
}

function initFridgeFeatures() {
  document.getElementById("fridge-notify-enable")?.addEventListener("click", () => {
    if (Notification.permission === "denied") {
      showToast("Open browser site settings and allow notifications for this page.", true);
      return;
    }
    requestFridgeNotifications();
  });
  document.getElementById("fridge-alert-btn")?.addEventListener("click", () => {
    showPanel("pantry", { scrollTo: "pantry-alerts-card" });
  });
  document.querySelectorAll(".expiry-preset").forEach((btn) => {
    btn.addEventListener("click", () => {
      const days = Number(btn.dataset.days) || 7;
      const inputEl = document.getElementById("pantry-expiry");
      if (inputEl) inputEl.value = defaultExpiryDate(days);
    });
  });
  initFoodScanner();
  if (fridgeNotifyEnabled() && Notification.permission === "granted") {
    startFridgeAlertPolling();
  }
}

function defaultExpiryDate(daysAhead = 7) {
  const d = new Date();
  d.setDate(d.getDate() + daysAhead);
  return d.toISOString().slice(0, 10);
}

function daysUntilExpiry(expiryDate) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const exp = new Date(`${expiryDate}T00:00:00`);
  return Math.round((exp - today) / 86400000);
}

function expiryStatus(expiryDate) {
  const days = daysUntilExpiry(expiryDate);
  if (days < 0) return { level: "expired", label: `Expired ${Math.abs(days)}d ago`, days };
  if (days === 0) return { level: "today", label: "Expires today", days };
  if (days <= 2) return { level: "soon", label: `Expires in ${days}d`, days };
  if (days <= 7) return { level: "week", label: `${days}d left`, days };
  return { level: "fresh", label: `${days}d left`, days };
}

function pantryItemIcon(ingredient) {
  const key = String(ingredient || "").toLowerCase();
  const icons = {
    egg: "🥚", eggs: "🥚", milk: "🥛", chicken: "🍗", rice: "🍚", tomato: "🍅",
    onion: "🧅", potato: "🥔", spinach: "🥬", bread: "🍞", cheese: "🧀",
    fish: "🐟", beef: "🥩", carrot: "🥕", apple: "🍎", banana: "🍌",
    garlic: "🧄", pasta: "🍝", pepper: "🫑", mushroom: "🍄", lemon: "🍋",
    butter: "🧈", oil: "🫒", basil: "🌿", bean: "🫘", corn: "🌽",
  };
  for (const [name, icon] of Object.entries(icons)) {
    if (key.includes(name)) return icon;
  }
  return "🥗";
}

function setPantryVisibility(showContent) {
  const guest = document.getElementById("pantry-guest");
  const shell = document.getElementById("pantry-shell");
  if (guest) guest.hidden = showContent;
  if (shell) shell.hidden = !showContent;
}

function initPantryFormDefaults() {
  const expiryInput = document.getElementById("pantry-expiry");
  if (expiryInput && !expiryInput.value) {
    expiryInput.value = defaultExpiryDate(7);
  }
}

function renderPantryHeader(items, alerts) {
  const el = document.getElementById("pantry-header");
  if (!el) return;
  const username = session?.username || "Chef";
  const urgent = alerts.filter((a) => daysUntilExpiry(a.expiry_date) <= 0).length;
  el.innerHTML = `
    <div class="pantry-header-icon" aria-hidden="true">🧊</div>
    <div class="pantry-header-body">
      <h3 class="pantry-header-title">${escapeHtml(username)}&apos;s digital fridge</h3>
      <p class="pantry-header-meta">${items.length} item${items.length === 1 ? "" : "s"} tracked${urgent ? ` · ${urgent} need attention` : ""}</p>
    </div>`;
}

function renderPantryQuickStats(items, alerts, lowStock) {
  const el = document.getElementById("pantry-quick-stats");
  if (!el) return;
  const expired = items.filter((i) => daysUntilExpiry(i.expiry_date) < 0).length;
  const expiringSoon = items.filter((i) => {
    const d = daysUntilExpiry(i.expiry_date);
    return d >= 0 && d <= 2;
  }).length;
  const fresh = items.filter((i) => daysUntilExpiry(i.expiry_date) > 7).length;
  el.innerHTML = `
    <div class="pantry-stat-card"><strong>${items.length}</strong><span>total items</span></div>
    <div class="pantry-stat-card pantry-stat-card--warn"><strong>${expiringSoon}</strong><span>expiring soon</span></div>
    <div class="pantry-stat-card pantry-stat-card--danger"><strong>${expired}</strong><span>expired</span></div>
    <div class="pantry-stat-card pantry-stat-card--ok"><strong>${fresh}</strong><span>fresh (7d+)</span></div>
    <div class="pantry-stat-card"><strong>${lowStock.length}</strong><span>staples missing</span></div>`;
}

function renderExpiryAlerts(alerts) {
  const alertsEl = document.getElementById("expiry-alerts");
  if (!alertsEl) return;
  if (!alerts.length) {
    alertsEl.innerHTML = `<div class="pantry-empty pantry-empty--compact"><span aria-hidden="true">✓</span><p>All clear — nothing expiring in the next 3 days.</p></div>`;
    return;
  }
  alertsEl.innerHTML = alerts
    .map((a) => {
      const status = expiryStatus(a.expiry_date);
      return `<div class="alert-card alert-card--${status.level}">
        <div class="alert-card-top">
          <span class="alert-card-icon">${pantryItemIcon(a.ingredient)}</span>
          <div>
            <strong>${escapeHtml(a.ingredient)}</strong>
            <span class="alert-card-date">${escapeHtml(a.expiry_date)} · ${escapeHtml(status.label)}</span>
          </div>
        </div>
        <p>${escapeHtml(a.message)}</p>
        <button type="button" class="btn ghost find-recipes" data-ingredient="${escapeAttr(a.ingredient)}">Find recipes</button>
      </div>`;
    })
    .join("");
  alertsEl.querySelectorAll(".find-recipes").forEach((btn) => {
    btn.addEventListener("click", () => {
      input.value = btn.dataset.ingredient;
      renderIngredientPills();
      showPanel("matcher");
    });
  });
}

function renderLowStock(lowStock) {
  const stockEl = document.getElementById("low-stock");
  if (!stockEl) return;
  if (!lowStock.length) {
    stockEl.innerHTML = "";
    stockEl.hidden = true;
    return;
  }
  stockEl.hidden = false;
  stockEl.innerHTML = `
    <div class="dash-card pantry-low-stock-card">
      <h3>Running low on staples</h3>
      <p class="muted">These common ingredients aren&apos;t in your pantry yet.</p>
      <div class="low-stock-chips">${lowStock
        .map(
          (s) =>
            `<button type="button" class="low-stock-chip" data-ingredient="${escapeAttr(s)}">${escapeHtml(s)}</button>`
        )
        .join("")}</div>
    </div>`;
  stockEl.querySelectorAll(".low-stock-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.getElementById("pantry-ingredient").value = btn.dataset.ingredient;
      document.getElementById("pantry-expiry").value = defaultExpiryDate(7);
      document.getElementById("pantry-ingredient").focus();
    });
  });
}

function renderPantryItems(items) {
  const list = document.getElementById("pantry-list");
  if (!list) return;
  if (!items.length) {
    list.innerHTML = `<div class="pantry-empty"><span aria-hidden="true">🧊</span><p>Your fridge is empty</p><p class="muted">Add ingredients with expiry dates to start tracking your inventory.</p></div>`;
    return;
  }
  list.innerHTML = items
    .map((item) => {
      const status = expiryStatus(item.expiry_date);
      return `<article class="pantry-item pantry-item--${status.level}">
        <div class="pantry-item-icon" aria-hidden="true">${pantryItemIcon(item.ingredient)}</div>
        <div class="pantry-item-body">
          <strong>${escapeHtml(item.ingredient)}</strong>
          <div class="pantry-item-meta">
            <span class="pantry-qty">Qty ${escapeHtml(item.qty)}</span>
            <span class="pantry-expiry-badge pantry-expiry-badge--${status.level}">${escapeHtml(status.label)}</span>
            <span class="pantry-expiry-date">${escapeHtml(item.expiry_date)}</span>
          </div>
        </div>
        <div class="pantry-item-actions">
          <button type="button" class="btn ghost find-recipes" data-ingredient="${escapeAttr(item.ingredient)}" title="Find recipes">Cook</button>
          <button type="button" class="btn ghost offer-surplus" data-ingredient="${escapeAttr(item.ingredient)}" data-qty="${escapeAttr(item.qty || "1")}" data-expiry="${escapeAttr(item.expiry_date || "")}" data-id="${escapeAttr(item._id)}" title="Share surplus">Share</button>
          <button type="button" class="btn ghost remove-pantry" data-id="${escapeAttr(item._id)}" title="Remove">Remove</button>
        </div>
      </article>`;
    })
    .join("");
  list.querySelectorAll(".find-recipes").forEach((btn) => {
    btn.addEventListener("click", () => {
      input.value = btn.dataset.ingredient;
      renderIngredientPills();
      showPanel("matcher");
    });
  });
  list.querySelectorAll(".offer-surplus").forEach((btn) => {
    btn.addEventListener("click", () => {
      openSurplusCompose({
        ingredient: btn.dataset.ingredient,
        qty: btn.dataset.qty,
        expiry_date: btn.dataset.expiry,
        pantry_item_id: btn.dataset.id,
      });
    });
  });
  list.querySelectorAll(".remove-pantry").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await api(`/api/pantry/${btn.dataset.id}?user_id=${encodeURIComponent(userId)}`, { method: "DELETE" });
        loadPantry();
      } catch (err) {
        setStatus(document.getElementById("pantry-status"), err.message, true);
      }
    });
  });
}

async function loadPantry() {
  const pantryStatus = document.getElementById("pantry-status");
  if (!userId) {
    setPantryVisibility(false);
    setStatus(pantryStatus, "");
    return;
  }
  setPantryVisibility(true);
  initPantryFormDefaults();
  if (!mongoAvailable) {
    setStatus(pantryStatus, "Connect MongoDB to manage your pantry.", true);
    return;
  }
  setStatus(pantryStatus, "Loading fridge…");
  try {
    const [pantry, alerts, stock] = await Promise.all([
      api(`/api/pantry?user_id=${encodeURIComponent(userId)}`),
      api(`/api/expiry-alerts?user_id=${encodeURIComponent(userId)}&days=3`),
      api(`/api/low-stock?user_id=${encodeURIComponent(userId)}`),
    ]);
    const items = pantry.items || [];
    const alertList = alerts.alerts || [];
    renderPantryHeader(items, alertList);
    renderPantryQuickStats(items, alertList, stock.low_stock || []);
    renderExpiryAlerts(alertList);
    renderLowStock(stock.low_stock || []);
    renderPantryItems(items);
    await handleFridgeAlerts(alertList);
    if (fridgeNotifyEnabled()) startFridgeAlertPolling();
    setStatus(pantryStatus, "");
    if (pendingShoppingMissing) {
      const missing = pendingShoppingMissing;
      pendingShoppingMissing = null;
      await loadShoppingList(missing);
    }
  } catch (err) {
    setStatus(pantryStatus, err.message, true);
  }
}

document.getElementById("pantry-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const pantryStatus = document.getElementById("pantry-status");
  if (!requireLogin("manage pantry")) return;
  if (!mongoAvailable) {
    setStatus(pantryStatus, "Start MongoDB to manage pantry.", true);
    return;
  }
  const ingredient = document.getElementById("pantry-ingredient").value.trim();
  const expiry_date = document.getElementById("pantry-expiry").value;
  const qty = document.getElementById("pantry-qty").value.trim() || "1";
  try {
    await api("/api/pantry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, ingredient, expiry_date, qty }),
    });
    e.target.reset();
    document.getElementById("pantry-qty").value = "1";
    loadPantry();
  } catch (err) {
    setStatus(pantryStatus, err.message, true);
  }
});

function initRecipeDialog() {
  document.getElementById("recipe-ingredients-close")?.addEventListener("click", () => {
    document.getElementById("recipe-ingredients-dialog")?.close();
  });
  document.getElementById("recipe-ingredients-dialog")?.addEventListener("click", (e) => {
    if (e.target.id === "recipe-ingredients-dialog") {
      e.target.close();
    }
  });
}

function profileInitials(name) {
  const parts = String(name || "U")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return parts[0].slice(0, 2).toUpperCase();
}

function formatProfileDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function isViewingOwnProfile(profile = null) {
  if (!userId) return false;
  const viewing = profileViewUserId || userId;
  if (viewing !== userId) return false;
  if (profile?.user_id && profile.user_id !== userId) return false;
  return true;
}

function renderProfileAvatar(profile, isOwn) {
  const username = profile.username || profile.user_id;
  const initials = profileInitials(username);
  const url = profile.avatar_url;
  const hasStory = !!profile.has_active_story;
  const seen = !!profile.story_seen;
  const ringClass = hasStory ? ` has-story${seen ? " story-seen" : ""}` : "";
  const img = url
    ? `<img class="profile-avatar-img" src="${escapeAttr(url)}" alt="" />`
    : `<div class="profile-avatar" aria-hidden="true">${initials}</div>`;
  const storyBtn = hasStory
    ? `<button type="button" class="profile-story-hit" data-story-user="${escapeAttr(profile.user_id)}" title="View story" aria-label="View story"></button>`
    : "";
  const addStory = isOwn
    ? `<button type="button" class="profile-story-add" id="profile-story-add" title="Add photo or video story" aria-label="Add photo or video story for 24 hours">+</button>`
    : "";
  const upload = isOwn
    ? `<label class="profile-avatar-upload" title="Change profile picture" aria-label="Change profile picture">
        <span class="profile-avatar-upload-icon" aria-hidden="true">✎</span>
        <span class="sr-only">Change profile picture</span>
        <input type="file" id="avatar-upload-input" accept="image/jpeg,image/png,image/webp,image/gif" />
      </label>`
    : "";
  return `<div class="profile-avatar-wrap${ringClass}" data-user-id="${escapeAttr(profile.user_id)}">${img}${storyBtn}${addStory}${upload}</div>`;
}

function storyTimeLabel(iso) {
  const d = new Date(iso || "");
  if (Number.isNaN(d.getTime())) return "Just now";
  const mins = Math.max(0, Math.round((Date.now() - d.getTime()) / 60000));
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return "Almost gone";
}

function stopStoryProgress() {
  if (storyProgressTimer) clearInterval(storyProgressTimer);
  storyProgressTimer = null;
}

function stopStoryMedia() {
  const video = document.getElementById("story-viewer-video");
  if (video) {
    video.pause();
    video.removeAttribute("src");
    video.load();
  }
  const image = document.getElementById("story-viewer-image");
  if (image) image.removeAttribute("src");
}

function updateStorySoundButton(muted) {
  const btn = document.getElementById("story-sound-btn");
  if (!btn) return;
  const on = btn.querySelector(".story-sound-on");
  const off = btn.querySelector(".story-sound-off");
  if (on) on.hidden = !!muted;
  if (off) off.hidden = !muted;
  btn.setAttribute("aria-label", muted ? "Unmute story" : "Mute story");
  btn.title = muted ? "Unmute" : "Mute";
}

function setStorySoundMuted(muted) {
  const video = document.getElementById("story-viewer-video");
  if (video) video.muted = !!muted;
  if (storyViewerState) storyViewerState.soundMuted = !!muted;
  updateStorySoundButton(!!muted);
}

async function playStoryVideoWithSound(video) {
  if (!video) return;
  const preferMuted = !!storyViewerState?.soundMuted;
  video.muted = preferMuted;
  updateStorySoundButton(video.muted);
  try {
    await video.play();
    return;
  } catch {
    /* try muted autoplay, then unmute on tap */
  }
  if (!video.muted) {
    video.muted = true;
    updateStorySoundButton(true);
    if (storyViewerState) storyViewerState.soundMuted = true;
    try {
      await video.play();
    } catch {
      /* blocked entirely */
    }
  }
}

function closeStoryViewer() {
  stopStoryProgress();
  stopStoryMedia();
  closeStoryViewersSheet();
  storyViewerState = null;
  const viewsBtn = document.getElementById("story-views-btn");
  if (viewsBtn) viewsBtn.hidden = true;
  const soundBtn = document.getElementById("story-sound-btn");
  if (soundBtn) soundBtn.hidden = true;
  const dialog = document.getElementById("story-viewer");
  if (dialog?.open) dialog.close();
}

function storyMediaIsVideo(story) {
  if (!story) return false;
  if (story.media_type === "video") return true;
  const url = String(story.media_url || "").toLowerCase();
  return /\.(mp4|webm|mov|avi)(\?|$)/.test(url);
}

function readVideoDuration(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const video = document.createElement("video");
    video.preload = "metadata";
    video.onloadedmetadata = () => {
      const duration = video.duration;
      URL.revokeObjectURL(url);
      resolve(Number.isFinite(duration) ? duration : 0);
    };
    video.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Could not read video"));
    };
    video.src = url;
  });
}

function renderStoryProgress(count, index, progress = 0) {
  const el = document.getElementById("story-progress");
  if (!el) return;
  el.innerHTML = Array.from({ length: count }, (_, i) => {
    const fill = i < index ? 100 : i === index ? Math.max(0, Math.min(100, progress)) : 0;
    return `<span class="story-progress-seg"><i style="width:${fill}%"></i></span>`;
  }).join("");
}

function closeStoryViewersSheet() {
  const sheet = document.getElementById("story-viewers-sheet");
  if (sheet) sheet.hidden = true;
}

function updateStoryViewsButton(story) {
  const btn = document.getElementById("story-views-btn");
  const label = document.getElementById("story-views-label");
  const isMine = !!(story && (story.mine || story.user_id === userId));
  if (!btn || !label) return;
  if (!isMine) {
    btn.hidden = true;
    closeStoryViewersSheet();
    return;
  }
  const n = Number(story.view_count) || 0;
  label.textContent = n === 1 ? "Seen by 1" : `Seen by ${n}`;
  btn.hidden = false;
}

async function openStoryViewersSheet() {
  const story = storyViewerState?.stories?.[storyViewerState.index];
  if (!story?.story_id || !userId) return;
  if (!(story.mine || story.user_id === userId)) return;
  stopStoryProgress();
  const sheet = document.getElementById("story-viewers-sheet");
  const list = document.getElementById("story-viewers-list");
  const note = document.getElementById("story-viewers-note");
  if (!sheet || !list) return;
  sheet.hidden = false;
  list.innerHTML = `<li class="story-viewers-empty">Loading…</li>`;
  if (note) note.textContent = "People who opened this story";
  try {
    const data = await api(
      `/api/stories/${encodeURIComponent(story.story_id)}/viewers?user_id=${encodeURIComponent(userId)}`
    );
    const viewers = data.viewers || [];
    story.view_count = data.view_count ?? viewers.length;
    updateStoryViewsButton(story);
    if (!viewers.length) {
      list.innerHTML = `<li class="story-viewers-empty">No one has viewed this story yet.</li>`;
      return;
    }
    list.innerHTML = viewers
      .map((v) => {
        const name = v.username || "User";
        const initials = profileInitials(name);
        const avatar = v.avatar_url
          ? `<img src="${escapeAttr(v.avatar_url)}" alt="" />`
          : `<span>${escapeHtml(initials)}</span>`;
        return `<li>
          <button type="button" class="story-viewer-row" data-user-id="${escapeAttr(v.user_id)}">
            <span class="story-viewer-row-avatar">${avatar}</span>
            <span class="story-viewer-row-name">${escapeHtml(name)}</span>
          </button>
        </li>`;
      })
      .join("");
  } catch (err) {
    list.innerHTML = `<li class="story-viewers-empty">${escapeHtml(err.message || "Could not load viewers.")}</li>`;
  }
}

function advanceStoryOrClose(index, stories) {
  if (!storyViewerState || storyViewerState.index !== index) return;
  stopStoryProgress();
  stopStoryMedia();
  if (index + 1 < stories.length) showStoryAt(index + 1);
  else closeStoryViewerAndRefresh();
}

function startStoryProgress(durationMs, index, stories, getPct) {
  stopStoryProgress();
  const started = Date.now();
  let pausedMs = 0;
  let pauseStarted = 0;
  storyProgressTimer = setInterval(() => {
    const sheet = document.getElementById("story-viewers-sheet");
    const sheetOpen = sheet && !sheet.hidden;
    const video = document.getElementById("story-viewer-video");
    if (sheetOpen) {
      if (!pauseStarted) {
        pauseStarted = Date.now();
        if (video && !video.paused) video.pause();
      }
      return;
    }
    if (pauseStarted) {
      pausedMs += Date.now() - pauseStarted;
      pauseStarted = 0;
      if (video && video.paused && video.src) video.play().catch(() => {});
    }
    const pct = typeof getPct === "function"
      ? getPct()
      : ((Date.now() - started - pausedMs) / durationMs) * 100;
    renderStoryProgress(stories.length, index, pct);
    if (pct >= 100) advanceStoryOrClose(index, stories);
  }, 40);
}

async function showStoryAt(index) {
  if (!storyViewerState?.stories?.length) return;
  const stories = storyViewerState.stories;
  const i = Math.max(0, Math.min(index, stories.length - 1));
  storyViewerState.index = i;
  const story = stories[i];
  const user = storyViewerState.user || {};
  const image = document.getElementById("story-viewer-image");
  const video = document.getElementById("story-viewer-video");
  const nameEl = document.getElementById("story-viewer-name");
  const timeEl = document.getElementById("story-viewer-time");
  const caption = document.getElementById("story-viewer-caption");
  const avatar = document.getElementById("story-viewer-avatar");
  const deleteBtn = document.getElementById("story-delete-btn");
  closeStoryViewersSheet();
  stopStoryProgress();
  stopStoryMedia();
  if (nameEl) nameEl.textContent = user.username || "Story";
  if (timeEl) timeEl.textContent = storyTimeLabel(story.created_at);
  if (avatar) {
    avatar.innerHTML = user.avatar_url
      ? `<img src="${escapeAttr(user.avatar_url)}" alt="" />`
      : profileInitials(user.username || "U");
  }
  const isVideo = storyMediaIsVideo(story);
  if (image) {
    image.hidden = isVideo;
    if (!isVideo) {
      image.src = story.media_url || "";
      image.alt = `${user.username || "User"} story`;
    }
  }
  const soundBtn = document.getElementById("story-sound-btn");
  if (soundBtn) soundBtn.hidden = !isVideo;
  if (video) {
    video.hidden = !isVideo;
    if (isVideo) {
      video.src = story.media_url || "";
      video.currentTime = 0;
      video.playsInline = true;
      video.muted = !!storyViewerState?.soundMuted;
      updateStorySoundButton(video.muted);
    }
  }
  if (caption) {
    const text = (story.caption || "").trim();
    caption.hidden = !text;
    caption.textContent = text;
  }
  if (deleteBtn) deleteBtn.hidden = !(story.mine || story.user_id === userId);
  updateStoryViewsButton(story);
  renderStoryProgress(stories.length, i, 0);

  // Start media immediately (keeps user-gesture for unmuted audio)
  if (isVideo && video) {
    const waitMeta = new Promise((resolve) => {
      if (video.readyState >= 1 && Number.isFinite(video.duration)) {
        resolve();
        return;
      }
      const done = () => {
        video.removeEventListener("loadedmetadata", done);
        resolve();
      };
      video.addEventListener("loadedmetadata", done);
      setTimeout(done, 1500);
    });
    const onEnded = () => {
      video.removeEventListener("ended", onEnded);
      advanceStoryOrClose(i, stories);
    };
    video.addEventListener("ended", onEnded);
    await playStoryVideoWithSound(video);
    await waitMeta;
    if (Number.isFinite(video.duration) && video.duration > 0) {
      const clipped = Math.min(video.duration, 30);
      startStoryProgress(clipped * 1000, i, stories, () => (video.currentTime / clipped) * 100);
    } else {
      startStoryProgress(15000, i, stories);
    }
  } else {
    startStoryProgress(5000, i, stories);
  }

  if (userId && story.story_id) {
    api(`/api/stories/${encodeURIComponent(story.story_id)}/view`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId }),
    })
      .then(() => {
        story.seen = true;
      })
      .catch(() => {});
  }
  if (userId && story.story_id && (story.mine || story.user_id === userId)) {
    api(`/api/stories/${encodeURIComponent(story.story_id)}/viewers?user_id=${encodeURIComponent(userId)}`)
      .then((data) => {
        if (!storyViewerState || storyViewerState.index !== i) return;
        story.view_count = data.view_count ?? 0;
        updateStoryViewsButton(story);
      })
      .catch(() => {});
  }
}

async function closeStoryViewerAndRefresh() {
  const targetId = storyViewerState?.user?.user_id;
  closeStoryViewer();
  if (session?.user_id) {
    await refreshSession();
    renderNavUserAvatar();
  }
  if (targetId && (profileViewUserId === targetId || (!profileViewUserId && targetId === userId))) {
    const panel = document.getElementById("profile");
    if (panel && !panel.hidden) loadProfile();
  }
}

async function openUserStory(targetUserId) {
  if (!targetUserId) return;
  try {
    const data = await api(
      `/api/stories/user/${encodeURIComponent(targetUserId)}?viewer_id=${encodeURIComponent(userId || "")}`
    );
    if (!data.stories?.length) {
      showToast("No active story right now.", false);
      return;
    }
    storyViewerState = {
      user: data.user || { user_id: targetUserId },
      stories: data.stories,
      index: 0,
      soundMuted: false,
    };
    const dialog = document.getElementById("story-viewer");
    if (dialog && !dialog.open) dialog.showModal();
    await showStoryAt(0);
  } catch (err) {
    showToast(err.message || "Could not open story.", true);
  }
}

async function uploadStory(file) {
  if (!requireLogin("post a story")) return;
  if (!file) return;
  const isVideo = String(file.type || "").startsWith("video/") || /\.(mp4|webm|mov|avi)$/i.test(file.name || "");
  const maxBytes = isVideo ? 25 * 1024 * 1024 : 8 * 1024 * 1024;
  if (file.size > maxBytes) {
    showToast(isVideo ? "Story video must be under 25 MB." : "Story image must be under 8 MB.", true);
    return;
  }
  if (isVideo) {
    try {
      const secs = await readVideoDuration(file);
      if (secs > 30.5) {
        showToast("Story videos can be up to 30 seconds.", true);
        return;
      }
    } catch {
      /* allow upload; server still validates type/size */
    }
  }
  try {
    showToast(isVideo ? "Uploading video story…" : "Uploading story…", false);
    const fd = new FormData();
    fd.append("user_id", userId);
    fd.append("file", file);
    const res = await fetch("/api/stories", { method: "POST", body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "Could not post story");
    showToast("Story posted for 24 hours.", false, {
      rich: true,
      variant: "success",
      title: "Story live",
      duration: 2800,
    });
    await refreshSession();
    renderNavUserAvatar();
    if (document.getElementById("profile") && !document.getElementById("profile").hidden) {
      await loadProfile();
    }
  } catch (err) {
    showToast(err.message || "Story upload failed.", true);
  }
}

function promptAddStory() {
  if (!requireLogin("post a story")) return;
  document.getElementById("story-upload-input")?.click();
}

function renderProfileBioDisplay(bio) {
  const text = (bio || "").trim();
  if (text) return `<p class="profile-bio-text">${escapeHtml(text)}</p>`;
  return `<p class="profile-bio-empty muted">No bio yet.</p>`;
}

function renderProfileDisplayName(name) {
  const text = (name || "").trim();
  if (!text) return "";
  return `<p class="profile-display-name">${escapeHtml(text)}</p>`;
}

function fillProfileEditor(profile = {}) {
  const bioEl = document.getElementById("profile-bio");
  const nameEl = document.getElementById("profile-display-name");
  const countryEl = document.getElementById("profile-country");
  const bio = (profile.bio || "").trim();
  const name = (profile.display_name || "").trim();
  const country = (profile.country || "PK").trim().toUpperCase() || "PK";
  if (bioEl) {
    bioEl.value = bio;
    bioEl.dataset.savedBio = bio;
    resizeProfileBio();
  }
  if (nameEl) {
    nameEl.value = name;
    nameEl.dataset.savedName = name;
  }
  if (countryEl) {
    if (![...countryEl.options].some((o) => o.value === country)) {
      countryEl.value = "PK";
    } else {
      countryEl.value = country;
    }
    countryEl.dataset.savedCountry = countryEl.value;
  }
  syncProfileSaveState();
}

function bindBioEditorOnce() {
  const form = document.getElementById("profile-bio-form");
  const bioEl = document.getElementById("profile-bio");
  const nameEl = document.getElementById("profile-display-name");
  const countryEl = document.getElementById("profile-country");
  if (!form || form.dataset.bound === "1") return;
  form.dataset.bound = "1";
  bioEl?.addEventListener("input", () => {
    resizeProfileBio();
    syncProfileSaveState();
  });
  nameEl?.addEventListener("input", syncProfileSaveState);
  countryEl?.addEventListener("change", syncProfileSaveState);
  form.addEventListener("submit", saveProfileDetails);
}

function renderProfileHeader(profile) {
  const el = document.getElementById("profile-header");
  if (!el) return;
  currentProfileData = profile;
  const isOwn = isViewingOwnProfile(profile);
  const username = profile.username || session?.username || profile.user_id;
  const displayName = (profile.display_name || "").trim();
  const roleLabel = profile.role === "admin" ? "Admin" : "";
  const member = profile.member_since ? `Joined ${formatProfileDate(profile.member_since)}` : "";
  const bio = (profile.bio || "").trim();
  const inactiveBadge = profile.is_active === false ? `<span class="profile-badge profile-badge--inactive">Not active</span>` : "";
  const privateBadge = profile.is_public === false ? `<span class="profile-badge profile-badge--private">Private</span>` : "";
  const social = [
    { value: profile.followers_count || 0, label: "Followers", key: "followers", clickable: true },
    { value: profile.following_count || 0, label: "Following", key: "following", clickable: true },
    { value: profile.posts_count || 0, label: "Posts", key: "posts", clickable: false },
  ];
  const socialHtml = social
    .map((s) => {
      const inner = `<strong>${s.value}</strong><span>${escapeHtml(s.label)}</span>`;
      if (s.clickable) {
        return `<button type="button" class="profile-social-stat profile-social-stat--btn" data-stat="${escapeAttr(s.key)}" data-user-id="${escapeAttr(profile.user_id)}" aria-label="View ${escapeAttr(s.label)}">${inner}</button>`;
      }
      return `<div class="profile-social-stat" data-stat="${escapeAttr(s.key)}">${inner}</div>`;
    })
    .join("");
  const nameBlock = renderProfileDisplayName(displayName);
  const bioBlock = renderProfileBioDisplay(bio);
  const editBtn = isOwn
    ? `<button type="button" class="btn ghost profile-edit-btn" id="profile-edit-btn" aria-expanded="${profileEditOpen ? "true" : "false"}" aria-label="${profileEditOpen ? "Close settings" : "Open settings"}" title="Settings">
        <svg class="profile-settings-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <circle cx="12" cy="12" r="3"/>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
        </svg>
      </button>`
    : "";
  el.innerHTML = `
    <div class="profile-header-top">
      ${renderProfileAvatar(profile, isOwn)}
      <div class="profile-identity">
        <div class="profile-name-row">
          <h3 class="profile-name">${escapeHtml(username)}</h3>
          ${roleLabel ? `<span class="profile-role">${escapeHtml(roleLabel)}</span>` : ""}
          ${privateBadge}
          ${inactiveBadge}
          ${editBtn}
        </div>
        ${nameBlock}
        ${member ? `<p class="profile-meta">${escapeHtml(member)}</p>` : ""}
        <div id="profile-social-stats" class="profile-social-stats" aria-label="Social stats">${socialHtml}</div>
      ${bioBlock}
    </div>
  </div>`;
  if (isOwn) {
    bindBioEditorOnce();
    fillProfileEditor(profile);
  }
  syncProfilePrivacyUi(profile);
}

function syncProfileSaveState() {
  const bioEl = document.getElementById("profile-bio");
  const nameEl = document.getElementById("profile-display-name");
  const countryEl = document.getElementById("profile-country");
  const btn = document.getElementById("profile-bio-save");
  const hint = document.getElementById("profile-bio-hint");
  if (!btn) return;
  const savedBio = bioEl?.dataset.savedBio ?? "";
  const savedName = nameEl?.dataset.savedName ?? "";
  const savedCountry = countryEl?.dataset.savedCountry ?? "PK";
  const dirty =
    (bioEl?.value ?? "") !== savedBio ||
    (nameEl?.value ?? "") !== savedName ||
    (countryEl?.value ?? "PK") !== savedCountry;
  btn.disabled = !dirty;
  btn.textContent = dirty ? "Save profile" : "Saved";
  if (hint) hint.hidden = true;
}

function setProfileEditOpen(open) {
  profileEditOpen = !!open;
  const panel = document.getElementById("profile-edit-panel");
  if (panel) panel.hidden = !profileEditOpen;
  const btn = document.getElementById("profile-edit-btn");
  if (btn) {
    btn.setAttribute("aria-expanded", profileEditOpen ? "true" : "false");
    btn.setAttribute("aria-label", profileEditOpen ? "Close settings" : "Open settings");
    btn.title = profileEditOpen ? "Close settings" : "Settings";
    btn.classList.toggle("is-open", profileEditOpen);
  }
  if (profileEditOpen && currentProfileData) {
    syncProfilePrivacyUi(currentProfileData);
    fillProfileEditor(currentProfileData);
    bindBioEditorOnce();
    document.getElementById("profile-display-name")?.focus();
  }
}

function syncProfilePrivacyUi(profile) {
  const isPublic = profile?.is_public !== false;
  const isActive = profile?.is_active !== false;
  document.getElementById("profile-privacy-public")?.classList.toggle("is-active", isPublic);
  document.getElementById("profile-privacy-private")?.classList.toggle("is-active", !isPublic);
  document.getElementById("profile-status-active")?.classList.toggle("is-active", isActive);
  document.getElementById("profile-status-inactive")?.classList.toggle("is-active", !isActive);
}

async function saveProfilePrivacy({ is_public, is_active } = {}) {
  if (!requireLogin("update account settings")) return;
  try {
    const body = { user_id: userId };
    if (typeof is_public === "boolean") body.is_public = is_public;
    if (typeof is_active === "boolean") body.is_active = is_active;
    const data = await api("/api/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    currentProfileData = data.profile || { ...currentProfileData, ...body };
    syncProfilePrivacyUi(currentProfileData);
    showToast(
      typeof is_public === "boolean"
        ? is_public
          ? "Profile is public."
          : "Profile is private."
        : is_active
          ? "Account is active."
          : "Account set to not active.",
      false
    );
    await loadProfile();
  } catch (err) {
    showToast(err.message || "Could not update settings.", true);
  }
}

async function openFollowList(targetUserId, kind) {
  if (!targetUserId) return;
  const dialog = document.getElementById("follow-list-dialog");
  const title = document.getElementById("follow-list-title");
  const body = document.getElementById("follow-list-body");
  if (!dialog || !body) return;
  const label = kind === "following" ? "Following" : "Followers";
  if (title) title.textContent = label;
  body.innerHTML = `<li class="follow-list-empty">Loading…</li>`;
  if (!dialog.open) dialog.showModal();
  try {
    const viewer = userId ? `?viewer_id=${encodeURIComponent(userId)}` : "";
    const path = kind === "following" ? "following" : "followers";
    const data = await api(`/api/users/${encodeURIComponent(targetUserId)}/${path}${viewer}`);
    const users = data.users || [];
    if (!users.length) {
      body.innerHTML = `<li class="follow-list-empty">No ${label.toLowerCase()} yet.</li>`;
      return;
    }
    body.innerHTML = users
      .map((u) => {
        const name = u.display_name || u.username || "User";
        const handle = u.username ? `@${u.username}` : "";
        const initials = profileInitials(u.username || name);
        const avatar = u.avatar_url
          ? `<img src="${escapeAttr(u.avatar_url)}" alt="" />`
          : `<span>${escapeHtml(initials)}</span>`;
        return `<li>
          <button type="button" class="follow-list-row" data-user-id="${escapeAttr(u.user_id)}">
            <span class="follow-list-avatar">${avatar}</span>
            <span class="follow-list-meta">
              <strong>${escapeHtml(name)}</strong>
              ${handle ? `<span class="muted">${escapeHtml(handle)}</span>` : ""}
            </span>
          </button>
        </li>`;
      })
      .join("");
  } catch (err) {
    body.innerHTML = `<li class="follow-list-empty">${escapeHtml(err.message || "Could not load list.")}</li>`;
  }
}

function closeFollowList() {
  const dialog = document.getElementById("follow-list-dialog");
  if (dialog?.open) dialog.close();
}

function applyProfileContentVisibility(profile, isOwn) {
  const canView = isOwn || profile.can_view_content !== false;
  const inactive = !isOwn && profile.is_active === false;
  const privateLocked = !isOwn && profile.is_active !== false && profile.can_view_content === false;
  const tabs = document.getElementById("profile-tabs");
  const privateLock = document.getElementById("profile-private-lock");
  const inactiveBanner = document.getElementById("profile-inactive-banner");
  if (inactiveBanner) inactiveBanner.hidden = !inactive;
  if (privateLock) privateLock.hidden = !privateLocked;
  if (tabs) tabs.hidden = !canView || inactive;
  document.querySelectorAll(".profile-tab-panel").forEach((p) => {
    if (!canView || inactive) p.hidden = true;
  });
  document.querySelectorAll('.profile-tab[data-profile-tab="saved"]').forEach((t) => {
    t.hidden = !isOwn;
  });
  if (!isOwn && profileTab === "saved") profileTab = "posts";
  if (canView && !inactive) setProfileTab(profileTab);
  if (!isOwn) setProfileEditOpen(false);
  const editPanel = document.getElementById("profile-edit-panel");
  if (editPanel && !isOwn) editPanel.hidden = true;
}

async function saveProfileDetails(e) {
  e?.preventDefault?.();
  e?.stopPropagation?.();
  if (!requireLogin("update profile")) return false;
  if (!mongoAvailable) {
    setStatus(document.getElementById("profile-status"), "Start MongoDB to save profile.", true);
    return false;
  }
  const bioEl = document.getElementById("profile-bio");
  const nameEl = document.getElementById("profile-display-name");
  const countryEl = document.getElementById("profile-country");
  if (!bioEl && !nameEl && !countryEl) return false;
  const bio = bioEl?.value || "";
  const displayName = (nameEl?.value || "").trim();
  const country = countryEl?.value || "PK";
  const btn = document.getElementById("profile-bio-save");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Saving…";
  }
  try {
    const data = await api("/api/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: userId,
        bio,
        display_name: displayName,
        country,
      }),
    });
    const profile = data.profile || {};
    currentProfileData = { ...(currentProfileData || {}), ...profile };
    fillProfileEditor(currentProfileData);
    renderProfileHeader(currentProfileData);
    renderImpactDashboard(currentProfileData);
    setProfileEditOpen(false);
    setStatus(document.getElementById("profile-status"), "Profile updated!");
    showToast("Profile updated.", false, {
      rich: true,
      variant: "success",
      icon: "✓",
      title: "Profile",
      duration: 3500,
    });
  } catch (err) {
    setStatus(document.getElementById("profile-status"), err.message, true);
    showToast(err.message, true, { rich: true, variant: "error", title: "Couldn’t save profile" });
    syncProfileSaveState();
  }
  return false;
}

function resizeProfileBio() {
  const el = document.getElementById("profile-bio");
  if (!el) return;
  el.style.height = "auto";
  const styles = window.getComputedStyle(el);
  const line = Number.parseFloat(styles.lineHeight) || 22;
  const pad =
    (Number.parseFloat(styles.paddingTop) || 0) + (Number.parseFloat(styles.paddingBottom) || 0);
  const min = Math.max(Math.round(line * 2 + pad), 56);
  const max = Math.round(line * 8 + pad);
  const next = Math.min(max, Math.max(min, el.scrollHeight || min));
  el.style.height = `${next}px`;
  el.style.overflowY = (el.scrollHeight || 0) > max ? "auto" : "hidden";
}

function renderProfileStats(profile) {
  const el = document.getElementById("profile-stats");
  if (!el) return;
  const isOwn = isViewingOwnProfile(profile);
  const totals = profile.totals || {};
  const tiles = [
    { value: profile.streak || 0, label: "Day streak", key: "streak" },
    { value: profile.points || 0, label: "Points", key: "points" },
    { value: totals.meals || 0, label: "Meals cooked", key: "meals" },
    { value: totals.ingredients_saved || 0, label: "Ingredients used", key: "ingredients" },
  ];
  const visible = tiles.filter((t) => t.value > 0);
  const activityZero = isOwn && !visible.length;
  const cards = (visible.length ? visible : isOwn ? [] : tiles)
    .map(
      (t, i) => `<div class="profile-stat-card" data-stat="${escapeAttr(t.key)}" style="animation-delay:${i * 0.04}s">
        <strong>${t.value}</strong><span>${escapeHtml(t.label)}</span>
      </div>`
    )
    .join("");
  const nudge = activityZero
    ? `<p class="profile-stats-nudge">Cook a recipe to start your streak and earn points.</p>`
    : "";
  el.innerHTML = `<div class="profile-stats-grid">${cards || ""}${nudge}</div>`;
  el.classList.toggle("profile-stats--sparse", activityZero);
}

function formatImpactKg(value) {
  const n = Number(value) || 0;
  if (n >= 10) return n.toFixed(1);
  if (n >= 1) return n.toFixed(2);
  return n.toFixed(2);
}

function renderImpactDashboard(profile, dash = null) {
  const el = document.getElementById("impact-dashboard");
  if (!el) return;
  const impact = dash?.impact || profile?.impact;
  const month = dash?.impact_month;
  const locationLabel = impact?.location_label || "your area";
  const monthLabel = dash?.month || "This month";
  if (!impact) {
    el.innerHTML = `<div class="impact-empty">
      <p>No impact data yet.</p>
      <p class="muted">${isViewingOwnProfile(profile || {}) ? "Cook leftover-based recipes to track money saved and waste reduced. Set your location in Settings." : "This cook hasn’t logged impact yet."}</p>
    </div>`;
    return;
  }
  const money = impact.money_saved_display || `${impact.currency_symbol || ""}${impact.money_saved || 0}`;
  const waste = formatImpactKg(impact.waste_reduced_kg);
  const co2 = formatImpactKg(impact.co2_avoided_kg);
  const monthMoney = month?.money_saved_display || "—";
  const monthWaste = month ? formatImpactKg(month.waste_reduced_kg) : "—";
  el.innerHTML = `
    <p class="impact-location">Estimates for <strong>${escapeHtml(locationLabel)}</strong> · based on leftovers you cook</p>
    <div class="impact-hero-grid">
      <article class="impact-card impact-card--money">
        <span class="impact-card-label">Money saved</span>
        <strong class="impact-card-value">${escapeHtml(money)}</strong>
        <span class="impact-card-meta">All time · ${impact.ingredients_saved || 0} ingredients kept in use</span>
      </article>
      <article class="impact-card impact-card--waste">
        <span class="impact-card-label">Food waste reduced</span>
        <strong class="impact-card-value">${escapeHtml(waste)} <small>kg</small></strong>
        <span class="impact-card-meta">≈ ${escapeHtml(co2)} kg CO₂ avoided</span>
      </article>
    </div>
    <div class="impact-month">
      <h4>${escapeHtml(monthLabel)}</h4>
      <div class="impact-month-grid">
        <div><strong>${escapeHtml(monthMoney)}</strong><span>Saved this month</span></div>
        <div><strong>${escapeHtml(String(monthWaste))} kg</strong><span>Waste avoided</span></div>
        <div><strong>${month?.meals_cooked ?? dash?.meals_created ?? 0}</strong><span>Meals cooked</span></div>
      </div>
    </div>
    <p class="muted impact-footnote">Rates use typical leftover food costs in ${escapeHtml(locationLabel)}. Change location in Profile → Settings.</p>
  `;
}

async function loadImpactDashboard(profile) {
  const el = document.getElementById("impact-dashboard");
  if (!el) return;
  const isOwn = isViewingOwnProfile(profile);
  if (!isOwn) {
    renderImpactDashboard(profile);
    return;
  }
  try {
    const dash = await api(`/api/dashboard?user_id=${encodeURIComponent(userId)}`);
    if (dash.impact && currentProfileData) currentProfileData.impact = dash.impact;
    if (dash.country && currentProfileData) currentProfileData.country = dash.country;
    renderImpactDashboard(profile, dash);
  } catch {
    renderImpactDashboard(profile);
  }
}

function renderProfileActionRow(profile) {
  const el = document.getElementById("profile-action-row");
  if (!el) return;
  const isOwn = isViewingOwnProfile(profile);
  if (isOwn || !userId || profile.is_active === false) {
    el.innerHTML = "";
    el.hidden = true;
    return;
  }
  el.hidden = false;
  const following = profile.is_following;
  el.innerHTML = `
    <button type="button" class="btn ${following ? "ghost" : "primary"}" id="profile-follow-btn" data-user-id="${escapeAttr(profile.user_id)}">${following ? "Following" : "Follow"}</button>
    <button type="button" class="btn ghost" id="profile-message-btn" data-user-id="${escapeAttr(profile.user_id)}">Message</button>`;
}

function renderSavedRestaurantsList(restaurants, isOwn) {
  const el = document.getElementById("saved-restaurants-list");
  const form = document.getElementById("save-restaurant-form");
  if (!el) return;
  if (form) form.hidden = !isOwn;
  if (!restaurants.length) {
    el.innerHTML = `<div class="profile-empty"><span aria-hidden="true">📍</span><p>No saved restaurants</p><p class="muted">${isOwn ? "Save spots from Discover or add one above." : "No restaurants saved yet."}</p></div>`;
    return;
  }
  el.innerHTML = restaurants
    .map((r) => {
      const saved = r.saved_at ? formatProfileDate(r.saved_at) : "";
      const removeBtn = isOwn
        ? `<button type="button" class="btn ghost remove-restaurant" data-id="${escapeAttr(r._id)}" title="Remove">Remove</button>`
        : "";
      const dir = r.directions_url
        ? `<a class="btn ghost" href="${escapeAttr(r.directions_url)}" target="_blank" rel="noopener">Directions</a>`
        : r.maps_url
          ? `<a class="btn ghost" href="${escapeAttr(r.maps_url)}" target="_blank" rel="noopener">Map</a>`
          : "";
      const meta = [r.cuisine, r.area || r.address].filter(Boolean).map((x) => escapeHtml(x)).join(" · ");
      return `<article class="profile-restaurant-card">
        <span class="profile-restaurant-icon" aria-hidden="true">📍</span>
        <div class="profile-restaurant-body">
          <strong>${escapeHtml(r.restaurant_name)}</strong>
          ${meta ? `<span>${meta}</span>` : ""}
          ${saved ? `<span>Saved ${escapeHtml(saved)}</span>` : ""}
        </div>
        ${dir}
        ${removeBtn}
      </article>`;
    })
    .join("");
}

async function loadRecommendedRestaurants() {
  const el = document.getElementById("recommended-restaurants");
  if (!el || !userId || !mongoAvailable) {
    if (el) el.hidden = true;
    return;
  }
  try {
    const data = await api(`/api/restaurants/recommended?user_id=${encodeURIComponent(userId)}&limit=6`);
    const items = data.restaurants || [];
    if (!items.length) {
      el.hidden = true;
      el.innerHTML = "";
      return;
    }
    el.hidden = false;
    el.innerHTML = `<p class="pref-recommend-label">Recommended for you</p>${items
      .map(
        (r) => `<article class="profile-restaurant-card profile-restaurant-card--rec">
        <span class="profile-restaurant-icon" aria-hidden="true">✨</span>
        <div class="profile-restaurant-body">
          <strong>${escapeHtml(r.restaurant_name)}</strong>
          <span class="muted">${escapeHtml(r.reason || "Based on your taste")}</span>
        </div>
        <button type="button" class="btn ghost save-recommended-restaurant" data-name="${escapeAttr(r.restaurant_name)}">Save</button>
      </article>`
      )
      .join("")}`;
    el.querySelectorAll(".save-recommended-restaurant").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await api("/api/saved-restaurants", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ user_id: userId, restaurant_name: btn.dataset.name, area: "" }),
          });
          showToast(`Saved ${btn.dataset.name}`);
          loadProfile();
        } catch (err) {
          showToast(err.message, true);
        }
      });
    });
  } catch {
    el.hidden = true;
  }
}

function showPrefBanner(elId, preferences, fallback = "") {
  const el = document.getElementById(elId);
  if (!el) return;
  if (!preferences?.active) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  const bits = [];
  if (preferences.top_cuisines?.length) bits.push(`cuisines: ${preferences.top_cuisines.slice(0, 3).join(", ")}`);
  if (preferences.allergies?.length) bits.push(`avoids: ${preferences.allergies.slice(0, 3).join(", ")}`);
  el.textContent = fallback || `Personalized from your taste${bits.length ? ` · ${bits.join(" · ")}` : ""}`;
  el.hidden = false;
}

function renderProfilePostsGrid(posts) {
  const el = document.getElementById("profile-posts-grid");
  if (!el) return;
  if (!posts.length) {
    el.classList.add("profile-posts-grid--empty");
    el.innerHTML = `<div class="profile-empty"><span class="profile-empty-icon" aria-hidden="true">◇</span><p>No recipe posts yet</p><p class="muted">Share a meal from Posts to fill this grid.</p></div>`;
    return;
  }
  el.classList.remove("profile-posts-grid--empty");
  el.innerHTML = posts
    .map((post) => {
      const media =
        post.media_type === "video"
          ? `<video src="${escapeAttr(post.media_url)}" muted playsinline preload="metadata"></video>`
          : `<img src="${escapeAttr(post.media_url)}" alt="${escapeAttr(post.caption || "Post")}" loading="lazy" />`;
      const caption = (post.caption || "").trim();
      return `<button type="button" class="profile-post-thumb" data-post-id="${escapeAttr(post.post_id)}" title="${escapeAttr(caption || "View post")}">
        ${media}
        ${caption ? `<span class="profile-post-caption">${escapeHtml(caption.slice(0, 42))}${caption.length > 42 ? "…" : ""}</span>` : ""}
      </button>`;
    })
    .join("");
}

async function openPostDetail(postId) {
  if (!postId) return;
  const dialog = document.getElementById("post-detail-dialog");
  const body = document.getElementById("post-detail-body");
  if (!dialog || !body) return;
  body.innerHTML = `<p class="muted" style="padding:1rem">Loading post…</p>`;
  if (!dialog.open) dialog.showModal();
  try {
    const viewer = userId ? `?viewer_id=${encodeURIComponent(userId)}` : "";
    const data = await api(`/api/posts/${encodeURIComponent(postId)}${viewer}`);
    const post = data.post;
    if (!post) throw new Error("Post not found");
    const existing = postsCache.findIndex((p) => p.post_id === post.post_id);
    if (existing >= 0) postsCache[existing] = post;
    else postsCache.unshift(post);
    body.innerHTML = renderPostCard(post, { showComments: true });
    const commentsPanel = body.querySelector(`#comments-${CSS.escape(post.post_id)}`);
    if (commentsPanel) {
      commentsPanel.hidden = false;
      await loadPostComments(post.post_id, commentsPanel);
    }
  } catch (err) {
    body.innerHTML = `<p class="status error" style="padding:1rem">${escapeHtml(err.message)}</p>`;
  }
}

function closePostDetail() {
  const dialog = document.getElementById("post-detail-dialog");
  if (dialog?.open) dialog.close();
}

function setProfileTab(tabName) {
  const allowed = new Set(["posts", "impact", "recipes", "saved"]);
  profileTab = allowed.has(tabName) ? tabName : "posts";
  document.querySelectorAll(".profile-tab").forEach((t) => {
    const on = t.dataset.profileTab === profileTab;
    t.classList.toggle("active", on);
    t.setAttribute("aria-selected", on ? "true" : "false");
  });
  document.querySelectorAll(".profile-tab-panel").forEach((p) => {
    p.hidden = p.dataset.profilePanel !== profileTab;
  });
  if (profileTab === "impact" && currentProfileData) {
    loadImpactDashboard(currentProfileData);
  }
}

function viewUserProfile(targetUserId) {
  if (!targetUserId) return;
  profileViewUserId = targetUserId;
  showPanel("profile");
  loadProfile();
}

function resetProfileView() {
  profileViewUserId = userId;
  loadProfile();
}

async function uploadAvatar(file) {
  const profileStatus = document.getElementById("profile-status");
  if (!requireLogin("update profile picture")) return;
  if (!file) return;
  const fd = new FormData();
  fd.append("user_id", userId);
  fd.append("file", file);
  setStatus(profileStatus, "Uploading photo…");
  try {
    const res = await fetch("/api/profile/avatar", { method: "POST", body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "Upload failed");
    if (session && data.avatar_url) {
      saveSession({ ...session, avatar_url: data.avatar_url });
      renderNavUserAvatar();
    } else {
      await refreshSession();
      renderNavUserAvatar();
    }
    setStatus(profileStatus, "Profile picture updated!");
    await loadProfile();
  } catch (err) {
    setStatus(profileStatus, err.message, true);
  }
}

async function toggleFollowUser(targetUserId, btn) {
  if (!requireLogin("follow users")) return;
  if (btn) btn.disabled = true;
  try {
    const data = await api(`/api/users/${encodeURIComponent(targetUserId)}/follow`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId }),
    });
    if (btn) {
      btn.textContent = data.following ? "Following" : "Follow";
      btn.classList.toggle("primary", !data.following);
      btn.classList.toggle("ghost", data.following);
    }
    const followersEl = document.querySelector('#profile-social-stats [data-stat="followers"] strong');
    if (followersEl && data.followers_count != null) followersEl.textContent = String(data.followers_count);
    if (data.following) showToast("Following user.");
  } catch (err) {
    showToast(err.message, true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function saveRestaurantFromForm(e) {
  e.preventDefault();
  const profileStatus = document.getElementById("profile-status");
  if (!requireLogin("save restaurants")) return;
  const name = document.getElementById("restaurant-name-input")?.value.trim();
  const area = document.getElementById("restaurant-area-input")?.value.trim() || "";
  if (!name) return;
  try {
    const data = await api("/api/saved-restaurants", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, restaurant_name: name, area }),
    });
    document.getElementById("save-restaurant-form")?.reset();
    setStatus(profileStatus, data.saved ? "Restaurant saved!" : "");
    await loadProfile();
  } catch (err) {
    setStatus(profileStatus, err.message, true);
  }
}

async function removeSavedRestaurant(restaurantId, btn) {
  const profileStatus = document.getElementById("profile-status");
  if (!requireLogin("manage saved restaurants")) return;
  if (btn) btn.disabled = true;
  try {
    await api(`/api/saved-restaurants/${encodeURIComponent(restaurantId)}?user_id=${encodeURIComponent(userId)}`, {
      method: "DELETE",
    });
    setStatus(profileStatus, "");
    await loadProfile();
  } catch (err) {
    setStatus(profileStatus, err.message, true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function saveRestaurantByName(name, area = "") {
  if (!requireLogin("save restaurants")) return;
  try {
    await api("/api/saved-restaurants", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, restaurant_name: name, area }),
    });
    showToast(`Saved ${name}.`);
  } catch (err) {
    showToast(err.message, true);
  }
}

async function openSavedRecipe(favoriteOrRecipe) {
  const snapshot = { ...(favoriteOrRecipe?.recipe || {}) };
  if (!snapshot.name && favoriteOrRecipe?.recipe_name) snapshot.name = favoriteOrRecipe.recipe_name;
  if (!snapshot.id && favoriteOrRecipe?.recipe_id) snapshot.id = favoriteOrRecipe.recipe_id;
  const recipeId = snapshot.id || favoriteOrRecipe?.recipe_id || "";
  let recipe = { ...snapshot };
  if (recipeId) {
    try {
      const data = await api(`/api/recipes/${encodeURIComponent(recipeId)}`);
      if (data.recipe) recipe = { ...snapshot, ...data.recipe };
    } catch {
      /* use saved snapshot (AI / external recipes) */
    }
  }
  if (!recipe.name) {
    showToast("Could not open this recipe.", true);
    return;
  }
  if (!recipe.image) {
    recipe.image = "https://www.themealdb.com/images/media/meals/ssrrrs1503664277.jpg";
  }
  if (recipe.match_score == null) recipe.match_score = 100;
  if (!Array.isArray(recipe.steps) || !recipe.steps.length) {
    const fromInstructions = String(recipe.instructions || "")
      .split(/(?<=\.)\s+/)
      .filter(Boolean);
    recipe.steps = fromInstructions.length ? fromInstructions : ["Open this recipe from Match next time after saving to keep full steps."];
  }
  showPanel("matcher");
  if (summaryEl) {
    summaryEl.hidden = true;
    summaryEl.innerHTML = "";
  }
  renderRecipes([recipe]);
  document.getElementById("results")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderFavoritesList(favorites, isOwn = true) {
  const el = document.getElementById("favorites-list");
  const clearBtn = document.getElementById("clear-favorites-btn");
  if (!el) return;
  if (clearBtn) clearBtn.hidden = !favorites.length || !isOwn;
  if (!favorites.length) {
    el.innerHTML = `<div class="profile-empty"><span aria-hidden="true">♡</span><p>No favorites yet</p><p class="muted">Heart a recipe from the matcher to save it here.</p></div>`;
    return;
  }
  el.innerHTML = favorites
    .map((f) => {
      const recipe = f.recipe || {};
      const name = f.recipe_name || recipe.name || "Recipe";
      const cuisine = recipe.cuisine ? `<span class="profile-recipe-tag">${escapeHtml(recipe.cuisine)}</span>` : "";
      const calories = recipe.calories ? `<span class="profile-recipe-tag">${recipe.calories} kcal</span>` : "";
      const saved = f.saved_at ? formatProfileDate(f.saved_at) : "";
      const recipeId = f.recipe_id || recipe.id || "";
      const payload = escapeAttr(JSON.stringify({
        recipe_id: recipeId,
        recipe_name: name,
        recipe,
      }));
      return `<article class="profile-recipe-card profile-recipe-card--link">
        <button type="button" class="profile-recipe-open" data-favorite="${payload}" title="Open recipe">
          <div class="profile-recipe-icon" aria-hidden="true">🍲</div>
          <div class="profile-recipe-body">
            <strong>${escapeHtml(name)}</strong>
            <div class="profile-recipe-meta">${cuisine}${calories}${saved ? `<span class="profile-recipe-date">Saved ${escapeHtml(saved)}</span>` : ""}</div>
          </div>
        </button>
        <div class="profile-item-actions">
          ${isOwn ? `<button type="button" class="btn ghost remove-favorite" data-id="${escapeAttr(f._id)}" data-recipe-id="${escapeAttr(recipeId)}" title="Remove from favorites">Remove</button>` : ""}
        </div>
      </article>`;
    })
    .join("");
  el.querySelectorAll(".profile-recipe-open").forEach((btn) => {
    btn.addEventListener("click", () => {
      try {
        openSavedRecipe(JSON.parse(btn.dataset.favorite || "{}"));
      } catch {
        showToast("Could not open this recipe.", true);
      }
    });
  });
}

function renderHistoryList(history, isOwn = true) {
  const el = document.getElementById("history-list");
  const clearBtn = document.getElementById("clear-history-btn");
  if (!el) return;
  if (clearBtn) clearBtn.hidden = !history.length || !isOwn;
  if (!history.length) {
    el.innerHTML = `<div class="profile-empty"><span aria-hidden="true">🍳</span><p>No cooking history yet</p><p class="muted">Mark a recipe as cooked to track meals here.</p></div>`;
    return;
  }
  el.innerHTML = history
    .map((h) => {
      const date = formatProfileDate(h.cooked_at);
      return `<article class="profile-history-item">
        <div class="profile-history-date">${escapeHtml(date)}</div>
        <div class="profile-history-body">
          <strong>${escapeHtml(h.recipe_name || "Recipe")}</strong>
        </div>
        <div class="profile-item-actions">
          ${isOwn ? `<button type="button" class="btn ghost remove-history" data-id="${escapeAttr(h._id)}" title="Remove from history">Remove</button>` : ""}
        </div>
      </article>`;
    })
    .join("");
}

async function removeFavorite(favoriteId, recipeId, btn) {
  const profileStatus = document.getElementById("profile-status");
  if (!favoriteId) {
    setStatus(profileStatus, "Could not remove favorite — missing item id.", true);
    return;
  }
  if (!requireLogin("manage favorites")) return;
  if (!mongoAvailable) {
    setStatus(profileStatus, "Start MongoDB to manage favorites.", true);
    return;
  }
  if (btn) btn.disabled = true;
  try {
    await api(`/api/favorites/${encodeURIComponent(favoriteId)}?user_id=${encodeURIComponent(userId)}`, {
      method: "DELETE",
    });
    if (recipeId) favoriteRecipeIds.delete(recipeId);
    document.querySelectorAll(`.fav-btn[data-recipe]`).forEach((btn) => {
      try {
        const recipe = JSON.parse(btn.dataset.recipe);
        if (recipe.id === recipeId) updateFavoriteButton(btn, false);
      } catch {
        /* ignore malformed data */
      }
    });
    setStatus(profileStatus, "");
    await loadProfile();
  } catch (err) {
    setStatus(profileStatus, err.message, true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function removeHistoryItem(historyId, btn) {
  const profileStatus = document.getElementById("profile-status");
  if (!historyId) {
    setStatus(profileStatus, "Could not remove history item — missing item id.", true);
    return;
  }
  if (!requireLogin("manage history")) return;
  if (!mongoAvailable) {
    setStatus(profileStatus, "Start MongoDB to manage history.", true);
    return;
  }
  if (btn) btn.disabled = true;
  try {
    await api(`/api/history/${encodeURIComponent(historyId)}?user_id=${encodeURIComponent(userId)}`, {
      method: "DELETE",
    });
    setStatus(profileStatus, "");
    await loadProfile();
  } catch (err) {
    setStatus(profileStatus, err.message, true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function clearAllFavorites() {
  const profileStatus = document.getElementById("profile-status");
  if (!requireLogin("manage favorites")) return;
  if (!mongoAvailable) {
    setStatus(profileStatus, "Start MongoDB to manage favorites.", true);
    return;
  }
  const ok = await askConfirm("This removes every recipe from your favorites list.", {
    title: "Clear favorites?",
    okLabel: "Remove all",
  });
  if (!ok) return;
  try {
    await api(`/api/favorites?user_id=${encodeURIComponent(userId)}`, { method: "DELETE" });
    favoriteRecipeIds = new Set();
    document.querySelectorAll(".fav-btn.is-favorited").forEach((btn) => updateFavoriteButton(btn, false));
    setStatus(profileStatus, "");
    await loadProfile();
  } catch (err) {
    setStatus(profileStatus, err.message, true);
  }
}

async function clearAllHistory() {
  const profileStatus = document.getElementById("profile-status");
  if (!requireLogin("manage history")) return;
  if (!mongoAvailable) {
    setStatus(profileStatus, "Start MongoDB to manage history.", true);
    return;
  }
  const ok = await askConfirm("This clears your recent cooking history.", {
    title: "Clear cooking history?",
    okLabel: "Clear history",
  });
  if (!ok) return;
  try {
    await api(`/api/history?user_id=${encodeURIComponent(userId)}`, { method: "DELETE" });
    setStatus(profileStatus, "");
    await loadProfile();
  } catch (err) {
    setStatus(profileStatus, err.message, true);
  }
}

function initProfileLists() {
  const shell = document.getElementById("profile-shell");
  shell?.addEventListener("click", (e) => {
    const favBtn = e.target.closest(".remove-favorite");
    if (favBtn) {
      e.preventDefault();
      removeFavorite(favBtn.dataset.id, favBtn.dataset.recipeId, favBtn);
      return;
    }
    const histBtn = e.target.closest(".remove-history");
    if (histBtn) {
      e.preventDefault();
      removeHistoryItem(histBtn.dataset.id, histBtn);
      return;
    }
    const restBtn = e.target.closest(".remove-restaurant");
    if (restBtn) {
      e.preventDefault();
      removeSavedRestaurant(restBtn.dataset.id, restBtn);
      return;
    }
    const storyAdd = e.target.closest("#profile-story-add");
    if (storyAdd) {
      e.preventDefault();
      document.getElementById("story-upload-input")?.click();
      return;
    }
    const storyHit = e.target.closest(".profile-story-hit");
    if (storyHit) {
      e.preventDefault();
      openUserStory(storyHit.dataset.storyUser);
      return;
    }
    const editBtn = e.target.closest("#profile-edit-btn");
    if (editBtn) {
      e.preventDefault();
      setProfileEditOpen(!profileEditOpen);
      return;
    }
    const socialStat = e.target.closest(".profile-social-stat--btn");
    if (socialStat) {
      e.preventDefault();
      openFollowList(socialStat.dataset.userId, socialStat.dataset.stat);
      return;
    }
    const followBtn = e.target.closest("#profile-follow-btn");
    if (followBtn) {
      e.preventDefault();
      toggleFollowUser(followBtn.dataset.userId, followBtn);
      return;
    }
    const messageBtn = e.target.closest("#profile-message-btn");
    if (messageBtn) {
      e.preventDefault();
      openDirectChatWithUser(messageBtn.dataset.userId);
      return;
    }
    const postThumb = e.target.closest(".profile-post-thumb");
    if (postThumb) {
      e.preventDefault();
      openPostDetail(postThumb.dataset.postId);
    }
  });
  document.getElementById("clear-favorites-btn")?.addEventListener("click", clearAllFavorites);
  document.getElementById("clear-history-btn")?.addEventListener("click", clearAllHistory);
  document.querySelectorAll(".profile-tab").forEach((tab) => {
    tab.addEventListener("click", () => setProfileTab(tab.dataset.profileTab || "posts"));
  });
  document.getElementById("profile-back-btn")?.addEventListener("click", () => {
    profileViewUserId = userId;
    profileEditOpen = false;
    const topBar = document.getElementById("profile-top-bar");
    const backBtn = document.getElementById("profile-back-btn");
    if (topBar) topBar.hidden = true;
    if (backBtn) backBtn.hidden = true;
    loadProfile();
  });
  document.getElementById("profile-privacy-public")?.addEventListener("click", () => saveProfilePrivacy({ is_public: true }));
  document.getElementById("profile-privacy-private")?.addEventListener("click", () => saveProfilePrivacy({ is_public: false }));
  document.getElementById("profile-status-active")?.addEventListener("click", () => saveProfilePrivacy({ is_active: true }));
  document.getElementById("profile-status-inactive")?.addEventListener("click", () => saveProfilePrivacy({ is_active: false }));
  document.getElementById("follow-list-close")?.addEventListener("click", closeFollowList);
  document.getElementById("follow-list-dialog")?.addEventListener("cancel", (e) => {
    e.preventDefault();
    closeFollowList();
  });
  document.getElementById("follow-list-body")?.addEventListener("click", (e) => {
    const row = e.target.closest(".follow-list-row");
    if (!row?.dataset.userId) return;
    closeFollowList();
    viewUserProfile(row.dataset.userId);
  });
  document.getElementById("save-restaurant-form")?.addEventListener("submit", saveRestaurantFromForm);
  shell?.addEventListener("change", (e) => {
    if (e.target.id === "avatar-upload-input") {
      uploadAvatar(e.target.files?.[0] || null);
      e.target.value = "";
    }
  });
}

function setProfileVisibility(showContent) {
  const guest = document.getElementById("profile-guest");
  const shell = document.getElementById("profile-shell");
  if (guest) guest.hidden = showContent;
  if (shell) shell.hidden = !showContent;
}

async function fetchProfileData(targetId) {
  const uid = encodeURIComponent(targetId);
  const viewer = userId ? `&viewer_id=${encodeURIComponent(userId)}` : "";
  try {
    return await api(`/api/profile?user_id=${uid}${viewer}`);
  } catch (err) {
    if (targetId !== userId) throw err;
    const dash = await api(`/api/dashboard?user_id=${uid}`);
    const created = dash.member_since || null;
    return {
      user_id: userId,
      username: session?.username || userId.replace(/_/g, " "),
      role: userRole,
      bio: "",
      avatar_url: null,
      allergies: dash.allergies || [],
      cuisines: dash.cuisines || [],
      points: dash.points || 0,
      streak: dash.streak || 0,
      badges: dash.badges || [],
      badge_catalog: dash.badge_catalog || [],
      totals: dash.all_time || {},
      country: dash.country || "PK",
      impact: dash.impact || null,
      member_since: created,
      followers_count: 0,
      following_count: 0,
      posts_count: 0,
      is_own_profile: true,
      is_public: true,
      is_active: true,
      can_view_content: true,
      _fallback: err.message,
    };
  }
}

async function loadProfile() {
  const profileStatus = document.getElementById("profile-status");
  if (!userId) {
    setProfileVisibility(false);
    const topBar = document.getElementById("profile-top-bar");
    if (topBar) topBar.hidden = true;
    setStatus(profileStatus, "");
    return;
  }
  if (!profileViewUserId) profileViewUserId = userId;
  const targetId = profileViewUserId || userId;
  const isOwn = targetId === userId;
  setProfileVisibility(true);
  const topBar = document.getElementById("profile-top-bar");
  const backBtn = document.getElementById("profile-back-btn");
  if (topBar) topBar.hidden = isOwn;
  if (backBtn) backBtn.hidden = isOwn;
  if (!mongoAvailable) {
    setStatus(profileStatus, "Connect MongoDB to view profiles.", true);
    return;
  }
  setStatus(profileStatus, "Loading profile…");
  try {
    const viewerQ = userId ? `viewer_id=${encodeURIComponent(userId)}&` : "";
    const [profile, fav, hist, postsData, restaurantsData] = await Promise.all([
      fetchProfileData(targetId),
      isOwn ? api(`/api/favorites?user_id=${encodeURIComponent(targetId)}`) : Promise.resolve({ favorites: [] }),
      api(`/api/users/${encodeURIComponent(targetId)}/recipes?${viewerQ}limit=30`),
      api(`/api/users/${encodeURIComponent(targetId)}/posts?${viewerQ}limit=30`),
      isOwn ? api(`/api/saved-restaurants?user_id=${encodeURIComponent(targetId)}`) : Promise.resolve({ restaurants: [] }),
    ]);
    renderProfileHeader(profile);
    applyProfileContentVisibility(profile, isOwn);
    renderProfileActionRow(profile);
    const canView = isOwn || profile.can_view_content !== false;
    if (canView && profile.is_active !== false) {
      renderProfileStats(profile);
      if (isOwn || profile.impact) loadImpactDashboard(profile);
      else {
        const impactEl = document.getElementById("impact-dashboard");
        if (impactEl) impactEl.innerHTML = "";
      }
      renderFavoritesList(isOwn ? fav.favorites || [] : [], isOwn);
      renderHistoryList(hist.recipes || [], isOwn);
      renderProfilePostsGrid(postsData.posts || []);
      renderSavedRestaurantsList(restaurantsData.restaurants || [], isOwn);
      if (isOwn) loadRecommendedRestaurants();
    } else {
      renderProfilePostsGrid([]);
      const histEl = document.getElementById("history-list");
      if (histEl) histEl.innerHTML = "";
      const statsEl = document.getElementById("profile-stats");
      if (statsEl) statsEl.innerHTML = "";
      const impactEl = document.getElementById("impact-dashboard");
      if (impactEl) impactEl.innerHTML = "";
    }
    if (!isOwn) {
      const rec = document.getElementById("recommended-restaurants");
      if (rec) {
        rec.hidden = true;
        rec.innerHTML = "";
      }
      const editPanel = document.getElementById("profile-edit-panel");
      if (editPanel) editPanel.hidden = true;
    } else if (profileEditOpen) {
      setProfileEditOpen(true);
    }
    if (profile._fallback) {
      setStatus(profileStatus, "Profile loaded (limited). Refresh if data looks incomplete.", true);
    } else {
      setStatus(profileStatus, "");
    }
  } catch (err) {
    setStatus(profileStatus, err.message, true);
  }
}

async function loadAdmin() {
  const adminStatus = document.getElementById("admin-status");
  const statsEl = document.getElementById("admin-stats");
  const usersEl = document.getElementById("admin-users");
  if (userRole !== "admin" || !userId) {
    statsEl.innerHTML = `<p class="muted">Admin access required. Log in with an admin account.</p>`;
    usersEl.innerHTML = "";
    return;
  }
  setStatus(adminStatus, "");
  try {
    const [stats, users] = await Promise.all([
      api(`/api/admin/stats?admin_user_id=${encodeURIComponent(userId)}`),
      api(`/api/admin/users?admin_user_id=${encodeURIComponent(userId)}`),
    ]);
    statsEl.innerHTML = `
      <h3>Platform stats</h3>
      <div class="stats">
        <div class="stat"><strong>${stats.registered_users}</strong><span>users</span></div>
        <div class="stat"><strong>${stats.admin_accounts}</strong><span>admins</span></div>
        <div class="stat"><strong>${stats.total_meals_cooked}</strong><span>meals</span></div>
        <div class="stat"><strong>${stats.pantry_items_tracked}</strong><span>pantry items</span></div>
      </div>`;
    usersEl.innerHTML = `
      <h3>User accounts</h3>
      <table class="admin-table">
        <thead><tr><th>Username</th><th>Role</th><th>Points</th><th>Meals</th><th>Actions</th></tr></thead>
        <tbody>${users.users
          .map(
            (u) => `
          <tr>
            <td>${escapeHtml(u.username || u.user_id)}</td>
            <td>${escapeHtml(u.role)}</td>
            <td>${u.points}</td>
            <td>${u.meals}</td>
            <td>${
              u.role !== "admin"
                ? `<button type="button" class="btn ghost make-admin" data-id="${escapeAttr(u.user_id)}">Make admin</button>`
                : `<button type="button" class="btn ghost make-user" data-id="${escapeAttr(u.user_id)}">Make user</button>`
            }</td>
          </tr>`
          )
          .join("")}</tbody>
      </table>`;
    usersEl.querySelectorAll(".make-admin").forEach((btn) => {
      btn.addEventListener("click", () => setUserRole(btn.dataset.id, "admin"));
    });
    usersEl.querySelectorAll(".make-user").forEach((btn) => {
      btn.addEventListener("click", () => setUserRole(btn.dataset.id, "user"));
    });
  } catch (err) {
    statsEl.innerHTML = `<p class="error">${escapeHtml(err.message)}</p>`;
  }
}

async function setUserRole(targetUserId, role) {
  const adminStatus = document.getElementById("admin-status");
  try {
    await api("/api/admin/role", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        admin_user_id: userId,
        target_user_id: targetUserId,
        role,
      }),
    });
    loadAdmin();
  } catch (err) {
    setStatus(adminStatus, err.message, true);
  }
}

let postsCache = [];

function notificationIcon(type) {
  if (type === "like") return "♥";
  if (type === "comment") return "💬";
  if (type === "reply") return "↩";
  if (type === "comment_like") return "♥";
  if (type === "follow") return "👤";
  if (type === "message") return "✉";
  return "🔔";
}

async function loadNotifications() {
  if (!userId || !mongoAvailable) return;
  const countEl = document.getElementById("notify-count");
  const notifyBtn = document.getElementById("notify-btn");
  try {
    const data = await api(`/api/notifications?user_id=${encodeURIComponent(userId)}&limit=30`);
    const unread = data.unread_count || 0;
    if (countEl) {
      countEl.hidden = unread === 0;
      countEl.textContent = unread > 99 ? "99+" : String(unread);
    }
    if (notifyBtn) {
      const tip =
        unread > 0
          ? `${unread} unread notification${unread === 1 ? "" : "s"}`
          : "Notifications";
      notifyBtn.title = tip;
      notifyBtn.setAttribute("aria-label", tip);
    }
    renderNotificationList(data.notifications || []);
  } catch {
    if (countEl) countEl.hidden = true;
  }
}

function renderNotificationList(items) {
  const list = document.getElementById("notify-list");
  if (!list) return;
  if (!items.length) {
    list.innerHTML = `<div class="notify-empty">No notifications yet.</div>`;
    return;
  }
  list.innerHTML = items
    .map((n) => {
      const time = n.created_at ? formatPostDate(n.created_at) : "";
      return `<button type="button" class="notify-item${n.read ? "" : " unread"}" data-notification-id="${escapeAttr(n.notification_id)}" data-post-id="${escapeAttr(n.post_id || "")}" data-actor-id="${escapeAttr(n.actor_id || "")}" data-type="${escapeAttr(n.type || "")}">
        <span class="notify-item-icon" aria-hidden="true">${notificationIcon(n.type)}</span>
        <span class="notify-item-body"><p>${escapeHtml(n.message || "")}</p>${time ? `<span class="notify-item-time">${escapeHtml(time)}</span>` : ""}</span>
      </button>`;
    })
    .join("");
}

function toggleNotifyPanel(forceOpen) {
  const panel = document.getElementById("notify-panel");
  if (!panel) return;
  const open = forceOpen === true ? true : forceOpen === false ? false : panel.hidden;
  panel.hidden = !open;
  if (open) loadNotifications();
}

async function markAllNotificationsRead() {
  if (!userId) return;
  try {
    await api("/api/notifications/read-all", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId }),
    });
    await loadNotifications();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function handleNotificationClick(item) {
  if (!userId || !item) return;
  const id = item.dataset.notificationId;
  try {
    await api(`/api/notifications/${encodeURIComponent(id)}/read`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId }),
    });
  } catch {
    /* ignore */
  }
  toggleNotifyPanel(false);
  const type = item.dataset.type;
  const actorId = item.dataset.actorId;
  if (type === "message" && actorId) {
    await openDirectChatWithUser(actorId);
    return;
  }
  if (type === "follow" && actorId) {
    viewUserProfile(actorId);
    return;
  }
  showPanel("posts");
  if (type === "like" || type === "comment" || type === "reply" || type === "comment_like") {
    postsView = "all";
    document.querySelectorAll(".posts-tab").forEach((t) => t.classList.toggle("active", t.dataset.postsView === "all"));
    await loadPosts();
  }
  loadNotifications();
}

function initNotifications() {
  document.getElementById("notify-btn")?.addEventListener("click", (e) => {
    e.stopPropagation();
    toggleNotifyPanel();
  });
  document.getElementById("notify-read-all")?.addEventListener("click", (e) => {
    e.stopPropagation();
    markAllNotificationsRead();
  });
  document.getElementById("notify-list")?.addEventListener("click", (e) => {
    const item = e.target.closest(".notify-item");
    if (item) handleNotificationClick(item);
  });
  document.addEventListener("click", (e) => {
    const wrap = document.getElementById("notify-wrap");
    const panel = document.getElementById("notify-panel");
    if (!wrap || !panel || panel.hidden) return;
    if (!wrap.contains(e.target)) panel.hidden = true;
  });
}

function startNotificationPolling() {
  if (notifyPollTimer) clearInterval(notifyPollTimer);
  if (!userId || !mongoAvailable) return;
  const tick = () => {
    if (document.hidden) return;
    loadNotifications();
  };
  notifyPollTimer = setInterval(tick, 90000);
  if (!notifyVisibilityBound) {
    notifyVisibilityBound = true;
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && userId && mongoAvailable) loadNotifications();
    });
  }
}

async function searchUsers(query) {
  const resultsEl = document.getElementById("user-search-results");
  if (!resultsEl) return;
  const q = query.trim();
  if (q.length < 2) {
    resultsEl.hidden = true;
    resultsEl.innerHTML = "";
    return;
  }
  try {
    const viewer = userId ? `&viewer_id=${encodeURIComponent(userId)}` : "";
    const data = await api(`/api/users/search?q=${encodeURIComponent(q)}${viewer}`);
    renderUserSearchResults(data.users || []);
  } catch (err) {
    resultsEl.hidden = false;
    resultsEl.innerHTML = `<div class="notify-empty">${escapeHtml(err.message)}</div>`;
  }
}

function renderUserSearchResults(users) {
  const resultsEl = document.getElementById("user-search-results");
  if (!resultsEl) return;
  if (!users.length) {
    resultsEl.hidden = false;
    resultsEl.innerHTML = `<div class="notify-empty">No users found.</div>`;
    return;
  }
  resultsEl.hidden = false;
  resultsEl.innerHTML = users
    .map((u) => {
      const avatar = u.avatar_url
        ? `<img src="${escapeAttr(u.avatar_url)}" alt="" />`
        : profileInitials(u.username || "U");
      const isSelf = u.user_id === userId;
      const followBtn =
        !isSelf && userId
          ? `<button type="button" class="btn ${u.is_following ? "ghost" : "primary"} user-search-follow" data-user-id="${escapeAttr(u.user_id)}">${u.is_following ? "Following" : "Follow"}</button>`
          : "";
      return `<div class="user-search-item">
        <span class="user-search-avatar">${avatar}</span>
        <div class="user-search-body" data-view-user="${escapeAttr(u.user_id)}">
          <strong>${escapeHtml(u.username || "User")}</strong>
          ${u.bio ? `<span>${escapeHtml(u.bio)}</span>` : ""}
        </div>
        ${followBtn}
      </div>`;
    })
    .join("");
}

function initUserSearch() {
  const input = document.getElementById("user-search-input");
  const resultsEl = document.getElementById("user-search-results");
  input?.addEventListener("input", () => {
    clearTimeout(userSearchTimer);
    userSearchTimer = setTimeout(() => searchUsers(input.value), 280);
  });
  resultsEl?.addEventListener("click", async (e) => {
    const followBtn = e.target.closest(".user-search-follow");
    if (followBtn) {
      e.stopPropagation();
      await toggleFollowUser(followBtn.dataset.userId, followBtn);
      searchUsers(input?.value || "");
      return;
    }
    const row = e.target.closest(".user-search-body[data-view-user]");
    if (row) {
      resultsEl.hidden = true;
      if (input) input.value = "";
      viewUserProfile(row.dataset.viewUser);
    }
  });
  document.addEventListener("click", (e) => {
    if (!resultsEl || resultsEl.hidden) return;
    if (!e.target.closest(".posts-search-row")) resultsEl.hidden = true;
  });
}

function setPostComposeType(type) {
  postComposeType = type === "reel" ? "reel" : "post";
  const isReel = postComposeType === "reel";
  document.getElementById("post-type-post")?.classList.toggle("is-active", !isReel);
  document.getElementById("post-type-reel")?.classList.toggle("is-active", isReel);
  const title = document.getElementById("posts-compose-title");
  if (title) title.textContent = isReel ? "Create reel" : "Create post";
  const labelText = document.getElementById("post-media-label-text");
  if (labelText) labelText.textContent = isReel ? "Short video" : "Photo or video";
  const dropHint = document.querySelector(".post-media-drop-hint");
  if (dropHint) {
    dropHint.textContent = isReel
      ? "Tap to upload · vertical video up to 30s"
      : "Tap to upload · JPG, PNG, MP4, WebM";
  }
  const hint = document.getElementById("post-reel-hint");
  if (hint) hint.hidden = !isReel;
  const caption = document.getElementById("post-caption");
  if (caption) caption.placeholder = isReel ? "Add a short caption…" : "What did you cook today?";
  const submit = document.getElementById("post-submit-btn");
  if (submit) submit.textContent = isReel ? "Share reel" : "Share post";
  const fileInput = document.getElementById("post-media");
  if (fileInput) {
    fileInput.accept = isReel
      ? "video/mp4,video/webm,video/quicktime,video/*"
      : "image/*,video/mp4,video/webm,video/quicktime";
    fileInput.value = "";
  }
  updatePostMediaPreview(null);
}

function setPostsComposeExpanded(expanded) {
  const card = document.getElementById("posts-compose-card");
  const prompt = document.getElementById("posts-compose-prompt");
  const body = document.getElementById("posts-compose-body");
  if (!card || !prompt || !body) return;
  card.classList.toggle("is-expanded", !!expanded);
  prompt.hidden = !!expanded;
  body.hidden = !expanded;
  if (expanded) {
    setPostComposeType(postComposeType);
    document.getElementById("post-caption")?.focus();
  }
}

function updatePostsAuthUi() {
  const guest = document.getElementById("posts-guest");
  const shell = document.getElementById("posts-shell");
  const compose = document.getElementById("posts-compose-card");
  const loggedIn = !!(userId && session?.username);
  if (guest) guest.hidden = loggedIn;
  if (shell) shell.hidden = false;
  if (compose) compose.hidden = !loggedIn;
  if (!loggedIn) setPostsComposeExpanded(false);
  document.querySelectorAll(".posts-tab[data-auth-only]").forEach((tab) => {
    tab.hidden = !loggedIn;
  });
  if (!loggedIn && (postsView === "following" || postsView === "saved" || postsView === "for_you")) {
    postsView = "trending";
    document.querySelectorAll(".posts-tab").forEach((t) => t.classList.toggle("active", t.dataset.postsView === "trending"));
  }
}

function formatPostDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  } catch {
    return iso;
  }
}

function renderPostMedia(post) {
  if (post.media_type === "video") {
    if (post.is_reel) {
      return `<div class="reel-inline-stage">
        <video class="post-media post-media--reel" src="${escapeAttr(post.media_url)}" muted loop playsinline controls preload="metadata"></video>
      </div>`;
    }
    return `<div class="post-media-stage">
      <video class="post-media" src="${escapeAttr(post.media_url)}" controls playsinline preload="metadata"></video>
    </div>`;
  }
  return `<div class="post-media-stage">
    <img class="post-media" src="${escapeAttr(post.media_url)}" alt="" loading="lazy" />
  </div>`;
}

function renderReelSlide(post) {
  const canDelete = userId && (post.user_id === userId || userRole === "admin");
  const usernameBtn = post.user_id
    ? `<button type="button" class="post-username-link reel-username" data-view-user="${escapeAttr(post.user_id)}">${escapeHtml(post.username || "User")}</button>`
    : `<strong class="reel-username">${escapeHtml(post.username || "User")}</strong>`;
  const caption = post.caption
    ? `<p class="reel-caption">${escapeHtml(post.caption)}</p>`
    : "";
  const tags = [
    post.recipe_tag ? `<span class="post-tag post-tag--recipe">🍲 ${escapeHtml(post.recipe_tag)}</span>` : "",
    post.restaurant_tag ? `<span class="post-tag post-tag--restaurant">📍 ${escapeHtml(post.restaurant_tag)}</span>` : "",
  ].filter(Boolean);
  return `<article class="reel-slide" data-post-id="${escapeAttr(post.post_id)}">
    <div class="reel-player">
      <div class="reel-backdrop" aria-hidden="true"></div>
      <video class="reel-video" src="${escapeAttr(post.media_url)}" muted loop playsinline preload="metadata"></video>
      <button type="button" class="reel-mute-btn" aria-label="Unmute" title="Unmute">🔇</button>
      <div class="reel-safe">
        <div class="reel-meta">
          <div class="reel-author">
            <div class="post-avatar reel-avatar" aria-hidden="true">${escapeHtml((post.username || "U").charAt(0).toUpperCase())}</div>
            <div class="reel-author-text">
              ${usernameBtn}
              <span class="post-date">${escapeHtml(formatPostDate(post.created_at))}</span>
            </div>
          </div>
          ${caption}
          ${tags.length ? `<div class="post-tags reel-tags">${tags.join("")}</div>` : ""}
        </div>
        <div class="reel-actions">
          <button type="button" class="btn ghost post-like reel-action${post.liked ? " is-liked" : ""}" data-id="${escapeAttr(post.post_id)}" aria-pressed="${post.liked}">
            <span class="reel-action-icon">${post.liked ? "♥" : "♡"}</span>
            <span>${post.likes_count || 0}</span>
          </button>
          <button type="button" class="btn ghost post-comment-toggle reel-action" data-id="${escapeAttr(post.post_id)}" aria-expanded="false">
            <span class="reel-action-icon">💬</span>
            <span>${post.comments_count || 0}</span>
          </button>
          <button type="button" class="btn ghost post-share reel-action" data-id="${escapeAttr(post.post_id)}">
            <span class="reel-action-icon">↗</span>
            <span>Share</span>
          </button>
          <button type="button" class="btn ghost post-bookmark reel-action${post.bookmarked ? " is-saved" : ""}" data-id="${escapeAttr(post.post_id)}" aria-pressed="${post.bookmarked}">
            <span class="reel-action-icon">🔖</span>
            <span>${post.bookmarked ? "Saved" : "Save"}</span>
          </button>
          ${canDelete ? `<button type="button" class="btn ghost post-delete reel-action" data-id="${escapeAttr(post.post_id)}" title="Delete" aria-label="Delete reel"><span class="reel-action-icon">🗑</span></button>` : ""}
        </div>
      </div>
      <div class="post-comments reel-comments" id="comments-${escapeAttr(post.post_id)}" hidden>
        <div class="post-comments-list"></div>
        <div class="post-comment-reply-hint" hidden>
          <span>Replying to <strong class="post-comment-reply-name"></strong></span>
          <button type="button" class="btn ghost post-comment-reply-cancel">Cancel</button>
        </div>
        <form class="post-comment-form">
          <input type="text" placeholder="Add a comment…" maxlength="500" required />
          <button type="submit" class="btn primary">Post</button>
        </form>
      </div>
    </div>
  </article>`;
}

function renderPostCard(post, { showComments = false } = {}) {
  const tags = [
    post.is_reel ? `<span class="post-tag post-tag--reel">Reel</span>` : "",
    post.recipe_tag ? `<span class="post-tag post-tag--recipe">🍲 ${escapeHtml(post.recipe_tag)}</span>` : "",
    post.restaurant_tag ? `<span class="post-tag post-tag--restaurant">📍 ${escapeHtml(post.restaurant_tag)}</span>` : "",
  ].filter(Boolean);
  const hashtags = (post.hashtags || []).map((t) => `<span class="post-hashtag">#${escapeHtml(t)}</span>`).join("");
  const canDelete = userId && (post.user_id === userId || userRole === "admin");
  const usernameBtn = post.user_id
    ? `<button type="button" class="post-username-link" data-view-user="${escapeAttr(post.user_id)}">${escapeHtml(post.username || "User")}</button>`
    : `<strong>${escapeHtml(post.username || "User")}</strong>`;
  const saveRestBtn =
    post.restaurant_tag && userId
      ? `<button type="button" class="btn ghost post-save-restaurant" data-restaurant="${escapeAttr(post.restaurant_tag)}" title="Save restaurant">📍 Save</button>`
      : "";
  return `<article class="post-card${post.is_reel ? " post-card--reel" : ""}${showComments ? " post-card--detail" : ""}" data-post-id="${escapeAttr(post.post_id)}">
    <header class="post-head">
      <div class="post-avatar" aria-hidden="true">${escapeHtml((post.username || "U").charAt(0).toUpperCase())}</div>
      <div class="post-head-meta">
        ${usernameBtn}
        <span class="post-date">${escapeHtml(formatPostDate(post.created_at))}</span>
      </div>
      ${saveRestBtn}
      ${canDelete ? `<button type="button" class="btn ghost post-delete" data-id="${escapeAttr(post.post_id)}" title="Delete post" aria-label="Delete post">🗑 Delete</button>` : ""}
    </header>
    ${renderPostMedia(post)}
    <div class="post-body">
      ${post.caption ? `<p class="post-caption">${escapeHtml(post.caption)}</p>` : ""}
      ${tags.length ? `<div class="post-tags">${tags.join("")}</div>` : ""}
      ${hashtags ? `<div class="post-hashtags">${hashtags}</div>` : ""}
      <div class="post-actions">
        <button type="button" class="btn ghost post-like${post.liked ? " is-liked" : ""}" data-id="${escapeAttr(post.post_id)}" aria-pressed="${post.liked}">
          ${post.liked ? "♥" : "♡"} <span>${post.likes_count || 0}</span>
        </button>
        <button type="button" class="btn ghost post-comment-toggle" data-id="${escapeAttr(post.post_id)}" aria-expanded="${showComments}">💬 <span>${post.comments_count || 0}</span></button>
        <button type="button" class="btn ghost post-share" data-id="${escapeAttr(post.post_id)}">↗ Share</button>
        <button type="button" class="btn ghost post-bookmark${post.bookmarked ? " is-saved" : ""}" data-id="${escapeAttr(post.post_id)}" aria-pressed="${post.bookmarked}">
          ${post.bookmarked ? "🔖 Saved" : "🔖 Save"}
        </button>
      </div>
      <div class="post-comments" id="comments-${escapeAttr(post.post_id)}"${showComments ? "" : " hidden"}>
        <div class="post-comments-list"></div>
        <div class="post-comment-reply-hint" hidden>
          <span>Replying to <strong class="post-comment-reply-name"></strong></span>
          <button type="button" class="btn ghost post-comment-reply-cancel">Cancel</button>
        </div>
        <form class="post-comment-form">
          <input type="text" placeholder="Add a comment…" maxlength="500" required />
          <button type="submit" class="btn primary">Post</button>
        </form>
      </div>
    </div>
  </article>`;
}

let reelPlaybackObserver = null;

function teardownReelPlayback() {
  if (reelPlaybackObserver) {
    reelPlaybackObserver.disconnect();
    reelPlaybackObserver = null;
  }
  document.querySelectorAll(".reel-video").forEach((v) => {
    try {
      v.pause();
    } catch {
      /* ignore */
    }
  });
}

function syncReelsMode(active) {
  document.body.classList.toggle("on-reels", !!active);
  if (!active) teardownReelPlayback();
}

function initReelPlayback(feed) {
  teardownReelPlayback();
  if (!feed) return;
  const videos = [...feed.querySelectorAll(".reel-slide .reel-video")];
  if (!videos.length) return;

  feed.querySelectorAll(".reel-mute-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const slide = btn.closest(".reel-slide");
      const video = slide?.querySelector(".reel-video");
      if (!video) return;
      video.muted = !video.muted;
      btn.textContent = video.muted ? "🔇" : "🔊";
      btn.setAttribute("aria-label", video.muted ? "Unmute" : "Mute");
      btn.title = video.muted ? "Unmute" : "Mute";
    });
  });

  feed.querySelectorAll(".reel-slide .reel-player").forEach((player) => {
    player.addEventListener("click", (e) => {
      if (e.target.closest("button, a, form, input, .reel-comments, .post-username-link")) return;
      const video = player.querySelector(".reel-video");
      if (!video) return;
      if (video.paused) video.play().catch(() => {});
      else video.pause();
    });
  });

  reelPlaybackObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        const video = entry.target.querySelector(".reel-video");
        if (!video) return;
        if (entry.isIntersecting && entry.intersectionRatio >= 0.65) {
          videos.forEach((v) => {
            if (v !== video) {
              try {
                v.pause();
              } catch {
                /* ignore */
              }
            }
          });
          video.play().catch(() => {});
        } else {
          try {
            video.pause();
          } catch {
            /* ignore */
          }
        }
      });
    },
    { root: feed, threshold: [0.65, 0.85] }
  );
  feed.querySelectorAll(".reel-slide").forEach((slide) => reelPlaybackObserver.observe(slide));
}

function renderPostsFeed(posts) {
  const feed = document.getElementById("posts-feed");
  if (!feed) return;
  postsCache = posts;
  const isReels = postsView === "reels";
  const immersiveReels = isReels && posts.length > 0;
  syncReelsMode(immersiveReels);
  feed.classList.toggle("posts-feed--reels", immersiveReels);
  if (!posts.length) {
    const emptyMsg = {
      following: "Follow people to see their posts here, or share your own!",
      trending: "No trending posts yet — like and comment to boost visibility.",
      for_you: "Personalize your feed by liking and saving posts.",
      reels: "Share a short cooking video and it’ll show up here.",
      all: "No posts yet — be the first to share what you cooked!",
      saved: "Bookmark posts to see them here.",
    };
    teardownReelPlayback();
    const cta =
      isReels && userId
        ? `<button type="button" class="btn primary" id="reels-empty-create">Create a reel</button>`
        : isReels
          ? `<button type="button" class="btn primary" id="reels-empty-login">Log in to create a reel</button>`
          : "";
    feed.innerHTML = `<div class="posts-empty${isReels ? " posts-empty--reels" : ""}">
      <span aria-hidden="true">${isReels ? "▶" : "📸"}</span>
      <p>${isReels ? "No reels yet" : "No posts yet"}</p>
      <p class="muted">${emptyMsg[postsView] || emptyMsg.all}</p>
      ${cta}
    </div>`;
    document.getElementById("reels-empty-create")?.addEventListener("click", () => {
      setPostComposeType("reel");
      setPostsComposeExpanded(true);
      document.getElementById("posts-compose-card")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
    document.getElementById("reels-empty-login")?.addEventListener("click", () => {
      document.getElementById("auth-dialog")?.showModal();
    });
    return;
  }
  if (isReels) {
    feed.innerHTML = posts.map(renderReelSlide).join("");
    requestAnimationFrame(() => {
      feed.scrollTop = 0;
      initReelPlayback(feed);
    });
    return;
  }
  teardownReelPlayback();
  feed.innerHTML = posts.map(renderPostCard).join("");
}

function formatCommentText(text) {
  const safe = escapeHtml(text || "");
  return safe.replace(/@([\w\u0080-\uFFFF]+)/g, '<span class="post-mention">@$1</span>');
}

function clearCommentReply(panel) {
  if (!panel) return;
  const form = panel.querySelector(".post-comment-form");
  const hint = panel.querySelector(".post-comment-reply-hint");
  if (form) {
    delete form.dataset.replyToCommentId;
    delete form.dataset.replyUsername;
  }
  if (hint) hint.hidden = true;
}

function startCommentReply(panel, commentId, username) {
  if (!panel || !userId) {
    requireLogin("reply to comments");
    return;
  }
  panel.hidden = false;
  const form = panel.querySelector(".post-comment-form");
  const hint = panel.querySelector(".post-comment-reply-hint");
  const input = form?.querySelector("input");
  const nameEl = hint?.querySelector(".post-comment-reply-name");
  if (form) {
    form.dataset.replyToCommentId = commentId;
    form.dataset.replyUsername = username;
  }
  if (hint) {
    hint.hidden = false;
    if (nameEl) nameEl.textContent = `@${username}`;
  }
  if (input) {
    const mention = `@${username} `;
    if (!input.value.trim().toLowerCase().startsWith(`@${username.toLowerCase()}`)) {
      input.value = mention;
    }
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  }
}

async function saveCommentEdit(postId, commentId, text, row) {
  if (!requireLogin("edit comments")) return;
  try {
    await api(`/api/posts/${encodeURIComponent(postId)}/comments/${encodeURIComponent(commentId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, text }),
    });
    const card = row.closest(".post-card, .reel-slide");
    const panel = card?.querySelector(".post-comments");
    if (panel) await loadPostComments(postId, panel);
  } catch (err) {
    showToast(err.message, true);
  }
}

function beginCommentEdit(row, postId, commentId, text) {
  if (row.dataset.editing === "1") return;
  row.dataset.editing = "1";
  row.innerHTML = `
    <div class="post-comment-edit">
      <textarea class="post-comment-edit-input" maxlength="500" rows="2">${escapeHtml(text)}</textarea>
      <div class="post-comment-edit-actions">
        <button type="button" class="btn primary post-comment-save-edit" data-post-id="${escapeAttr(postId)}" data-comment-id="${escapeAttr(commentId)}">Save</button>
        <button type="button" class="btn ghost post-comment-cancel-edit" data-post-id="${escapeAttr(postId)}">Cancel</button>
      </div>
    </div>`;
  row.querySelector(".post-comment-edit-input")?.focus();
}

async function loadPostComments(postId, container) {
  const list = container.querySelector(".post-comments-list");
  if (!list) return;
  list.innerHTML = `<p class="muted">Loading comments…</p>`;
  const post = postsCache.find((p) => p.post_id === postId);
  const postOwnerId = post?.user_id;
  try {
    const data = await api(
      `/api/posts/${encodeURIComponent(postId)}/comments${userId ? `?viewer_id=${encodeURIComponent(userId)}` : ""}`
    );
    const comments = data.comments || [];
    list.innerHTML = comments.length
      ? comments
          .map((c) => {
            const isAuthor = userId && c.user_id === userId;
            const canDelete =
              userId &&
              (c.user_id === userId || postOwnerId === userId || userRole === "admin");
            const replyLabel = c.reply_to_username
              ? `<span class="post-comment-reply-label">↩ @${escapeHtml(c.reply_to_username)}</span>`
              : "";
            const editedLabel = c.edited_at ? `<span class="post-comment-edited">edited</span>` : "";
            const actions = [];
            if (userId) {
              actions.push(
                `<button type="button" class="btn ghost post-comment-like${c.liked ? " is-liked" : ""}" data-post-id="${escapeAttr(postId)}" data-comment-id="${escapeAttr(c.comment_id)}" aria-pressed="${c.liked}" title="Like comment">${c.liked ? "♥" : "♡"} <span>${c.likes_count || 0}</span></button>`
              );
              actions.push(
                `<button type="button" class="btn ghost post-comment-reply" data-post-id="${escapeAttr(postId)}" data-comment-id="${escapeAttr(c.comment_id)}" data-username="${escapeAttr(c.username)}" title="Reply">↩ Reply</button>`
              );
            } else if (c.likes_count) {
              actions.push(`<span class="post-comment-like-count" aria-hidden="true">♥ ${c.likes_count}</span>`);
            }
            if (isAuthor) {
              actions.push(
                `<button type="button" class="btn ghost post-comment-edit" data-post-id="${escapeAttr(postId)}" data-comment-id="${escapeAttr(c.comment_id)}" title="Edit">✎ Edit</button>`
              );
            }
            if (canDelete) {
              actions.push(
                `<button type="button" class="btn ghost post-comment-delete" data-post-id="${escapeAttr(postId)}" data-comment-id="${escapeAttr(c.comment_id)}" title="Delete">🗑</button>`
              );
            }
            return `<div class="post-comment${c.reply_to_comment_id ? " post-comment--reply" : ""}" data-comment-id="${escapeAttr(c.comment_id)}">
              <div class="post-comment-body">
                <div class="post-comment-head">
                  <strong>${escapeHtml(c.username)}</strong>
                  ${replyLabel}
                  ${c.created_at ? `<time class="post-comment-time">${escapeHtml(formatPostDate(c.created_at))}</time>` : ""}
                  ${editedLabel}
                </div>
                <p class="post-comment-text">${formatCommentText(c.text)}</p>
              </div>
              ${actions.length ? `<div class="post-comment-actions">${actions.join("")}</div>` : ""}
            </div>`;
          })
          .join("")
      : `<p class="muted post-comments-empty">No comments yet.</p>`;
  } catch (err) {
    list.innerHTML = `<p class="muted">${escapeHtml(err.message)}</p>`;
  }
}

async function toggleCommentLike(postId, commentId, btn) {
  if (!requireLogin("like comments")) return;
  try {
    const data = await api(
      `/api/posts/${encodeURIComponent(postId)}/comments/${encodeURIComponent(commentId)}/like`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId }),
      }
    );
    if (btn) {
      btn.classList.toggle("is-liked", data.liked);
      btn.setAttribute("aria-pressed", String(data.liked));
      btn.innerHTML = `${data.liked ? "♥" : "♡"} <span>${data.likes_count}</span>`;
    }
  } catch (err) {
    showToast(err.message, true);
  }
}

async function deleteComment(postId, commentId, btn) {
  if (!requireLogin("delete comments")) return;
  if (btn) btn.disabled = true;
  try {
    const data = await api(
      `/api/posts/${encodeURIComponent(postId)}/comments/${encodeURIComponent(commentId)}?user_id=${encodeURIComponent(userId)}`,
      { method: "DELETE" }
    );
    const card = findPostCard(postId);
    const panel = card?.querySelector(".post-comments");
    if (panel) await loadPostComments(postId, panel);
    setCommentToggleCount(card, data.comments_count);
    const cached = postsCache.find((p) => p.post_id === postId);
    if (cached) cached.comments_count = data.comments_count;
  } catch (err) {
    showToast(err.message, true);
    if (btn) btn.disabled = false;
  }
}

async function loadPosts() {
  const statusEl = document.getElementById("posts-status");
  updatePostsAuthUi();
  if (!mongoAvailable) {
    setStatus(statusEl, "Connect MongoDB to use food posts.", true);
    return;
  }
  if (!userId && (postsView === "following" || postsView === "saved" || postsView === "for_you")) {
    postsView = "trending";
  }
  setStatus(statusEl, "Loading posts…");
  try {
    let path;
    if (postsView === "saved") {
      if (!userId) {
        openAuthDialog("login");
        setStatus(statusEl, "Log in to view saved posts.", true);
        return;
      }
      path = `/api/posts/bookmarks?user_id=${encodeURIComponent(userId)}`;
    } else {
      const viewer = userId ? `user_id=${encodeURIComponent(userId)}&` : "";
      const view = !userId && postsView === "following" ? "all" : postsView;
      path = `/api/posts?${viewer}view=${encodeURIComponent(view)}&limit=30`;
    }
    const data = await api(path);
    renderPostsFeed(data.posts || []);
    setStatus(statusEl, "");
  } catch (err) {
    setStatus(statusEl, err.message, true);
  }
}

async function togglePostLike(postId, btn) {
  if (!requireLogin("like posts")) return;
  try {
    const data = await api(`/api/posts/${encodeURIComponent(postId)}/like`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId }),
    });
    btn.classList.toggle("is-liked", data.liked);
    btn.setAttribute("aria-pressed", String(data.liked));
    if (btn.classList.contains("reel-action")) {
      btn.innerHTML = `<span class="reel-action-icon">${data.liked ? "♥" : "♡"}</span><span>${data.likes_count}</span>`;
    } else {
      btn.innerHTML = `${data.liked ? "♥" : "♡"} <span>${data.likes_count}</span>`;
    }
  } catch (err) {
    showToast(err.message, true);
  }
}

async function togglePostBookmark(postId, btn) {
  if (!requireLogin("save posts")) return;
  try {
    const data = await api(`/api/posts/${encodeURIComponent(postId)}/bookmark`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId }),
    });
    btn.classList.toggle("is-saved", data.bookmarked);
    btn.setAttribute("aria-pressed", String(data.bookmarked));
    if (btn.classList.contains("reel-action")) {
      btn.innerHTML = `<span class="reel-action-icon">🔖</span><span>${data.bookmarked ? "Saved" : "Save"}</span>`;
    } else {
      btn.textContent = data.bookmarked ? "🔖 Saved" : "🔖 Save";
    }
    if (postsView === "saved") loadPosts();
  } catch (err) {
    showToast(err.message, true);
  }
}

function findPostCard(postId) {
  const id = CSS.escape(postId);
  return (
    document.querySelector(`.post-card[data-post-id="${id}"]`) ||
    document.querySelector(`.reel-slide[data-post-id="${id}"]`)
  );
}

function setCommentToggleCount(card, count) {
  if (!card || count == null) return;
  const btn = card.querySelector(".post-comment-toggle");
  if (!btn) return;
  const spans = btn.querySelectorAll("span");
  const countEl = spans.length > 1 ? spans[spans.length - 1] : spans[0] || null;
  if (countEl) countEl.textContent = String(count);
}

async function deletePost(postId, btn) {
  if (!requireLogin("delete posts")) return;
  const ok = await askConfirm("This cannot be undone.", {
    title: "Delete this post?",
    okLabel: "Delete post",
  });
  if (!ok) return;
  if (btn) btn.disabled = true;
  try {
    await api(`/api/posts/${encodeURIComponent(postId)}?user_id=${encodeURIComponent(userId)}`, {
      method: "DELETE",
    });
    postsCache = postsCache.filter((p) => p.post_id !== postId);
    findPostCard(postId)?.remove();
    if (!document.querySelector("#posts-feed .post-card, #posts-feed .reel-slide")) {
      renderPostsFeed([]);
    }
  } catch (err) {
    showToast(err.message, true);
    if (btn) btn.disabled = false;
  }
}

async function sharePost(postId) {
  const post = postsCache.find((p) => p.post_id === postId);
  if (!post) return;
  const text = [post.caption, post.recipe_tag ? `Recipe: ${post.recipe_tag}` : "", post.restaurant_tag ? `@ ${post.restaurant_tag}` : ""]
    .filter(Boolean)
    .join("\n");
  const url = `${location.origin}${location.pathname}#posts`;
  try {
    if (navigator.share) {
      await navigator.share({ title: `Petugram · ${post.username}`, text, url });
      return;
    }
  } catch {
    /* fall through */
  }
  try {
    await navigator.clipboard.writeText(`${text}\n${url}`.trim());
    showToast("Post link copied to clipboard.");
  } catch {
    showToast("Share this post from Petugram!", false);
  }
}

function updatePostMediaPreview(file) {
  const preview = document.getElementById("post-media-preview");
  if (!preview) return;
  if (!file) {
    preview.hidden = true;
    preview.innerHTML = "";
    return;
  }
  preview.hidden = false;
  const url = URL.createObjectURL(file);
  if (file.type.startsWith("video/")) {
    preview.innerHTML = `<video src="${escapeAttr(url)}" controls playsinline></video>`;
  } else {
    preview.innerHTML = `<img src="${escapeAttr(url)}" alt="Preview" />`;
  }
}

function initPosts() {
  document.getElementById("posts-compose-prompt")?.addEventListener("click", () => setPostsComposeExpanded(true));
  document.getElementById("posts-compose-collapse")?.addEventListener("click", () => setPostsComposeExpanded(false));
  document.getElementById("post-type-post")?.addEventListener("click", () => setPostComposeType("post"));
  document.getElementById("post-type-reel")?.addEventListener("click", () => setPostComposeType("reel"));
  document.getElementById("post-media")?.addEventListener("change", (e) => {
    updatePostMediaPreview(e.target.files?.[0] || null);
  });

  document.querySelectorAll(".posts-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      postsView = tab.dataset.postsView || "feed";
      document.querySelectorAll(".posts-tab").forEach((t) => t.classList.toggle("active", t === tab));
      if (postsView !== "reels") syncReelsMode(false);
      loadPosts();
    });
  });

  document.getElementById("post-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const statusEl = document.getElementById("posts-status");
    const isReel = postComposeType === "reel";
    if (!requireLogin(isReel ? "share reels" : "create posts")) return;
    if (!mongoAvailable) {
      setStatus(statusEl, "Connect MongoDB to share posts.", true);
      return;
    }
    const fileInput = document.getElementById("post-media");
    const file = fileInput?.files?.[0];
    if (!file) {
      setStatus(statusEl, isReel ? "Choose a short video for your reel." : "Choose a photo or video to upload.", true);
      return;
    }
    if (isReel) {
      const isVideo = String(file.type || "").startsWith("video/") || /\.(mp4|webm|mov|avi)$/i.test(file.name || "");
      if (!isVideo) {
        setStatus(statusEl, "Reels must be a video file.", true);
        return;
      }
      if (file.size > 40 * 1024 * 1024) {
        setStatus(statusEl, "Reel video must be under 40 MB.", true);
        return;
      }
      try {
        const secs = await readVideoDuration(file);
        if (secs > 30.5) {
          setStatus(statusEl, "Reels can be up to 30 seconds.", true);
          return;
        }
      } catch {
        /* allow upload; server still validates type/size */
      }
    }
    const submitBtn = document.getElementById("post-submit-btn");
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = "Uploading…";
    }
    const fd = new FormData();
    fd.append("user_id", userId);
    fd.append("caption", document.getElementById("post-caption")?.value || "");
    fd.append("hashtags", document.getElementById("post-hashtags")?.value || "");
    fd.append("recipe_tag", document.getElementById("post-recipe-tag")?.value || "");
    fd.append("restaurant_tag", document.getElementById("post-restaurant-tag")?.value || "");
    fd.append("is_reel", isReel ? "true" : "false");
    fd.append("file", file);
    try {
      const res = await fetch("/api/posts", { method: "POST", body: fd });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = data.detail;
        let message = Array.isArray(detail)
          ? detail.map((d) => d.msg || String(d)).join(", ")
          : detail || data.message || `Upload failed (${res.status})`;
        if (res.status === 404) {
          message = "Posts API not found — restart the server and install python-multipart.";
        }
        throw new Error(message);
      }
      document.getElementById("post-form")?.reset();
      updatePostMediaPreview(null);
      setPostsComposeExpanded(false);
      postsView = isReel ? "reels" : "trending";
      document.querySelectorAll(".posts-tab").forEach((t) => t.classList.toggle("active", t.dataset.postsView === postsView));
      setPostComposeType("post");
      setStatus(statusEl, isReel ? "Reel shared!" : "Post shared!");
      showToast(isReel ? "Your reel is live!" : "Your food post is live!");
      await loadPosts();
    } catch (err) {
      setStatus(statusEl, err.message, true);
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = postComposeType === "reel" ? "Share reel" : "Share post";
      }
    }
  });

  const onPostFeedClick = async (e) => {
    const likeBtn = e.target.closest(".post-like");
    if (likeBtn) {
      e.preventDefault();
      await togglePostLike(likeBtn.dataset.id, likeBtn);
      return;
    }
    const bookmarkBtn = e.target.closest(".post-bookmark");
    if (bookmarkBtn) {
      e.preventDefault();
      await togglePostBookmark(bookmarkBtn.dataset.id, bookmarkBtn);
      return;
    }
    const shareBtn = e.target.closest(".post-share");
    if (shareBtn) {
      e.preventDefault();
      await sharePost(shareBtn.dataset.id);
      return;
    }
    const deleteBtn = e.target.closest(".post-delete");
    if (deleteBtn) {
      e.preventDefault();
      await deletePost(deleteBtn.dataset.id, deleteBtn);
      closePostDetail();
      if (document.getElementById("profile") && !document.getElementById("profile").hidden) {
        loadProfile();
      }
      return;
    }
    const userLink = e.target.closest(".post-username-link[data-view-user]");
    if (userLink) {
      e.preventDefault();
      closePostDetail();
      viewUserProfile(userLink.dataset.viewUser);
      return;
    }
    const saveRestBtn = e.target.closest(".post-save-restaurant");
    if (saveRestBtn) {
      e.preventDefault();
      await saveRestaurantByName(saveRestBtn.dataset.restaurant || "");
      return;
    }
    const commentToggle = e.target.closest(".post-comment-toggle");
    if (commentToggle) {
      e.preventDefault();
      const postId = commentToggle.dataset.id;
      const panel = document.getElementById(`comments-${postId}`);
      if (!panel) return;
      const opening = panel.hidden;
      panel.hidden = !opening;
      if (opening) await loadPostComments(postId, panel);
      return;
    }
    const commentDeleteBtn = e.target.closest(".post-comment-delete");
    if (commentDeleteBtn) {
      e.preventDefault();
      await deleteComment(commentDeleteBtn.dataset.postId, commentDeleteBtn.dataset.commentId, commentDeleteBtn);
      return;
    }
    const commentLikeBtn = e.target.closest(".post-comment-like");
    if (commentLikeBtn) {
      e.preventDefault();
      await toggleCommentLike(commentLikeBtn.dataset.postId, commentLikeBtn.dataset.commentId, commentLikeBtn);
      return;
    }
    const commentReplyBtn = e.target.closest(".post-comment-reply");
    if (commentReplyBtn) {
      e.preventDefault();
      const panel = commentReplyBtn.closest(".post-comments");
      startCommentReply(panel, commentReplyBtn.dataset.commentId, commentReplyBtn.dataset.username);
      return;
    }
    const commentEditBtn = e.target.closest(".post-comment-edit");
    if (commentEditBtn) {
      e.preventDefault();
      const row = commentEditBtn.closest(".post-comment");
      const text = row?.querySelector(".post-comment-text")?.textContent?.trim() || "";
      beginCommentEdit(row, commentEditBtn.dataset.postId, commentEditBtn.dataset.commentId, text);
      return;
    }
    const saveEditBtn = e.target.closest(".post-comment-save-edit");
    if (saveEditBtn) {
      e.preventDefault();
      const row = saveEditBtn.closest(".post-comment");
      const text = row?.querySelector(".post-comment-edit-input")?.value.trim();
      if (!text) return;
      await saveCommentEdit(saveEditBtn.dataset.postId, saveEditBtn.dataset.commentId, text, row);
      return;
    }
    const cancelEditBtn = e.target.closest(".post-comment-cancel-edit");
    if (cancelEditBtn) {
      e.preventDefault();
      await loadPostComments(cancelEditBtn.dataset.postId, cancelEditBtn.closest(".post-comments"));
      return;
    }
    const replyCancelBtn = e.target.closest(".post-comment-reply-cancel");
    if (replyCancelBtn) {
      e.preventDefault();
      const panel = replyCancelBtn.closest(".post-comments");
      clearCommentReply(panel);
      const input = panel?.querySelector(".post-comment-form input");
      if (input) input.value = "";
    }
  };

  const onPostFeedSubmit = async (e) => {
    const form = e.target.closest(".post-comment-form");
    if (!form) return;
    e.preventDefault();
    if (!requireLogin("comment on posts")) return;
    const card = form.closest(".post-card, .reel-slide");
    const postId = card?.dataset.postId;
    const input = form.querySelector("input");
    const submitBtn = form.querySelector('button[type="submit"]');
    const text = input?.value.trim();
    if (!postId || !text) return;
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = "Posting…";
    }
    try {
      const commentForm = card.querySelector(".post-comment-form");
      const payload = { user_id: userId, text };
      if (commentForm?.dataset.replyToCommentId) {
        payload.reply_to_comment_id = commentForm.dataset.replyToCommentId;
      }
      const data = await api(`/api/posts/${encodeURIComponent(postId)}/comments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (input) input.value = "";
      const panel = card.querySelector(".post-comments");
      clearCommentReply(panel);
      if (panel) {
        panel.hidden = false;
        await loadPostComments(postId, panel);
        panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
      const count = data.comments_count;
      setCommentToggleCount(card, count);
      const cached = postsCache.find((p) => p.post_id === postId);
      if (cached && count != null) cached.comments_count = count;
      showToast("Comment posted.");
    } catch (err) {
      showToast(err.message, true);
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = "Post";
      }
    }
  };

  ["posts-feed", "post-detail-body"].forEach((id) => {
    const el = document.getElementById(id);
    el?.addEventListener("click", onPostFeedClick);
    el?.addEventListener("submit", onPostFeedSubmit);
  });

  document.getElementById("post-detail-close")?.addEventListener("click", closePostDetail);
  document.getElementById("post-detail-dialog")?.addEventListener("click", (e) => {
    if (e.target.id === "post-detail-dialog") closePostDetail();
  });
}

function setMessagesVisibility(loggedIn) {
  const guest = document.getElementById("messages-guest");
  const shell = document.getElementById("messages-shell");
  if (guest) {
    guest.hidden = !!loggedIn;
    guest.setAttribute("aria-hidden", loggedIn ? "true" : "false");
  }
  if (shell) {
    shell.hidden = !loggedIn;
    shell.setAttribute("aria-hidden", loggedIn ? "false" : "true");
  }
}

async function loadMsgUnreadBadge() {
  const badge = document.getElementById("msg-nav-badge");
  if (!badge || !userId || !mongoAvailable) return;
  try {
    const data = await api(`/api/messages/unread?user_id=${encodeURIComponent(userId)}`);
    const count = data.unread_count || 0;
    badge.hidden = count === 0;
    badge.textContent = count > 99 ? "99+" : String(count);
  } catch {
    badge.hidden = true;
  }
}

function startMessageUnreadPolling() {
  if (msgUnreadTimer) clearInterval(msgUnreadTimer);
  if (!userId || !mongoAvailable) return;
  msgUnreadTimer = setInterval(() => {
    if (!document.hidden) loadMsgUnreadBadge();
  }, 30000);
}

function stopMessageUnreadPolling() {
  if (msgUnreadTimer) clearInterval(msgUnreadTimer);
  msgUnreadTimer = null;
}

function stopMessageThreadPolling() {
  if (msgPollTimer) clearInterval(msgPollTimer);
  msgPollTimer = null;
}

function formatMsgListTime(iso) {
  const d = parseMsgDate(iso);
  if (!d) return "";
  const diff = Date.now() - d.getTime();
  if (diff < 45000) return "Now";
  if (diff < 3600000) return `${Math.max(1, Math.floor(diff / 60000))}m`;
  if (diff < 86400000) return `${Math.max(1, Math.floor(diff / 3600000))}h`;
  if (diff < 604800000) return d.toLocaleDateString(undefined, { weekday: "short" });
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function parseMsgDate(iso) {
  if (!iso) return null;
  try {
    // Treat naive ISO (no Z/offset) as UTC — server times are UTC.
    const raw = String(iso);
    const normalized = /[zZ]|[+-]\d{2}:\d{2}$/.test(raw) ? raw : `${raw}Z`;
    const d = new Date(normalized);
    return Number.isNaN(d.getTime()) ? null : d;
  } catch {
    return null;
  }
}

function formatMsgBubbleTime(iso) {
  const d = parseMsgDate(iso);
  if (!d) return "";
  return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

function formatMsgDayLabel(iso) {
  const d = parseMsgDate(iso);
  if (!d) return "";
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  const sameDay = (a, b) =>
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  if (sameDay(d, today)) return "Today";
  if (sameDay(d, yesterday)) return "Yesterday";
  return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

function msgDayKey(iso) {
  const d = parseMsgDate(iso);
  if (!d) return "";
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

function setMessagesChatOpen(open) {
  document.getElementById("messages-layout")?.classList.toggle("chat-open", !!open);
}

function closeMessageSearch() {
  const resultsEl = document.getElementById("msg-user-results");
  const clearBtn = document.getElementById("msg-search-clear");
  const searchInput = document.getElementById("msg-user-search");
  if (resultsEl) {
    resultsEl.hidden = true;
    resultsEl.innerHTML = "";
  }
  if (searchInput) searchInput.value = "";
  if (clearBtn) clearBtn.hidden = true;
}

function resizeComposeInput() {
  const input = document.getElementById("msg-compose-input");
  if (!input) return;
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
}

function isThreadNearBottom(thread, threshold = 80) {
  if (!thread) return true;
  return thread.scrollHeight - thread.scrollTop - thread.clientHeight < threshold;
}

function peerDisplayName(peer = {}) {
  const display = String(peer.display_name || "").trim();
  if (display) return display;
  const username = String(peer.username || "").trim();
  if (username) {
    if (username.includes(" ") || username.length > 3) {
      return username
        .split(/\s+/)
        .filter(Boolean)
        .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
        .join(" ");
    }
    return username;
  }
  const id = String(peer.user_id || "").replace(/_/g, " ").trim();
  return id || "Chat";
}

function peerHandle(peer = {}) {
  const username = String(peer.username || "").trim();
  if (!username) return "";
  const display = peerDisplayName(peer);
  if (username.toLowerCase() === display.toLowerCase()) return "";
  return username.startsWith("@") ? username : `@${username}`;
}

function setChatPeerHeader(peer = {}) {
  msgActivePeer = peer;
  const title = document.getElementById("msg-chat-title");
  const avatar = document.getElementById("msg-chat-avatar");
  const peerBtn = document.getElementById("msg-chat-peer");
  const hint = peerBtn?.querySelector(".msg-chat-peer-hint");
  const name = peerDisplayName(peer);
  const handle = peerHandle(peer);
  if (title) title.textContent = name;
  if (avatar) {
    avatar.classList.toggle("msg-avatar-short", name.length <= 3);
    avatar.innerHTML = peer.avatar_url
      ? `<img src="${escapeAttr(peer.avatar_url)}" alt="" />`
      : profileInitials(name);
  }
  if (hint) hint.textContent = handle ? `${handle} · View profile` : "View profile";
  if (peerBtn) {
    peerBtn.hidden = !peer.user_id;
    peerBtn.dataset.userId = peer.user_id || "";
    peerBtn.classList.toggle("is-short-name", name.length <= 3);
  }
}

const MSG_QUICK_REACTIONS = ["❤️", "😂", "🔥", "👍", "😮", "😢", "👏", "🎉"];
let msgEmojiCatalog = [];
let msgStickerPacks = [];
let msgActiveStickerPackId = "";
let msgEmojiSearchTimer = null;
let msgEmojiLoaded = false;

function encodeStickerMessage({ packId = "", stickerId = "", emoji = "" } = {}) {
  if (packId && stickerId && emoji) return `::petugram-sticker:${packId}:${stickerId}:${emoji}::`;
  return `::petugram-sticker:${emoji}::`;
}

function parseStickerMessage(text) {
  const raw = String(text || "").trim();
  const packed = raw.match(/^::petugram-sticker:([a-z0-9_-]+):([a-z0-9_-]+):(.+?)::$/u);
  if (packed) {
    return {
      packId: packed[1],
      stickerId: packed[2],
      emoji: packed[3],
      imageUrl: resolveStickerImage(packed[1], packed[2], packed[3]),
    };
  }
  const legacy = raw.match(/^::petugram-sticker:(.+?)::$/u);
  if (!legacy) return null;
  return { packId: "", stickerId: "", emoji: legacy[1], imageUrl: "" };
}

function emojiToTwemojiUrl(emoji) {
  const code = [...String(emoji || "")]
    .filter((ch) => ch.codePointAt(0) !== 0xfe0f)
    .map((ch) => ch.codePointAt(0).toString(16))
    .join("-");
  return code ? `https://cdn.jsdelivr.net/gh/jdecked/twemoji@15.1.0/assets/72x72/${code}.png` : "";
}

function resolveStickerImage(packId, stickerId, emoji) {
  for (const pack of msgStickerPacks) {
    if (pack.id !== packId) continue;
    const hit = (pack.stickers || []).find((s) => s.id === stickerId);
    if (hit?.image_url) return hit.image_url;
  }
  return emojiToTwemojiUrl(emoji);
}

function isEmojiOnlyMessage(text) {
  const t = String(text || "").trim();
  if (!t || t.length > 16) return false;
  if (/[A-Za-z0-9]/.test(t)) return false;
  return /^[\p{Extended_Pictographic}\uFE0F\u200D\s]+$/u.test(t);
}

function formatMsgPreviewText(raw) {
  const sticker = parseStickerMessage(raw);
  if (sticker) return `Sticker ${sticker.emoji}`;
  return raw || "No messages yet";
}

function renderEmojiPanelItems(emojis) {
  const emojiPanel = document.getElementById("msg-emoji-panel");
  if (!emojiPanel) return;
  if (!emojis.length) {
    emojiPanel.innerHTML = `<div class="msg-emoji-empty">No emoji found</div>`;
    return;
  }
  emojiPanel.innerHTML = emojis
    .map((e) => {
      const char = e.char || e.emoji || "";
      const name = e.name || char;
      const img = e.image_url
        ? `<img src="${escapeAttr(e.image_url)}" alt="" loading="lazy" />`
        : `<span>${char}</span>`;
      return `<button type="button" class="msg-emoji-item" data-emoji="${escapeAttr(char)}" title="${escapeAttr(name)}" aria-label="Insert ${escapeAttr(name)}">${img}</button>`;
    })
    .join("");
}

function renderStickerPackTabs() {
  const tabs = document.getElementById("msg-sticker-pack-tabs");
  if (!tabs) return;
  tabs.innerHTML = msgStickerPacks
    .map((pack) => {
      const active = pack.id === msgActiveStickerPackId ? " active" : "";
      const cover = pack.cover_image
        ? `<img src="${escapeAttr(pack.cover_image)}" alt="" />`
        : `<span>${pack.cover || "✨"}</span>`;
      return `<button type="button" class="msg-sticker-pack-tab${active}" data-pack-id="${escapeAttr(pack.id)}" title="${escapeAttr(pack.name)}" aria-label="${escapeAttr(pack.name)} pack">${cover}</button>`;
    })
    .join("");
}

function renderActiveStickerPack() {
  const stickerPanel = document.getElementById("msg-sticker-panel");
  if (!stickerPanel) return;
  const pack = msgStickerPacks.find((p) => p.id === msgActiveStickerPackId) || msgStickerPacks[0];
  if (!pack) {
    stickerPanel.innerHTML = `<div class="msg-emoji-empty">No sticker packs yet</div>`;
    return;
  }
  msgActiveStickerPackId = pack.id;
  stickerPanel.innerHTML = `
    <div class="msg-sticker-pack-head">
      <strong>${escapeHtml(pack.name)}</strong>
      <span class="muted">${escapeHtml(pack.description || "")}</span>
    </div>
    <div class="msg-sticker-grid">
      ${(pack.stickers || [])
        .map((s) => {
          const visual = s.image_url
            ? `<img src="${escapeAttr(s.image_url)}" alt="" loading="lazy" />`
            : `<span>${s.emoji}</span>`;
          return `<button type="button" class="msg-sticker-item" data-pack-id="${escapeAttr(pack.id)}" data-sticker-id="${escapeAttr(s.id)}" data-sticker="${escapeAttr(s.emoji)}" title="${escapeAttr(s.label)}" aria-label="Send ${escapeAttr(s.label)} sticker">${visual}<small>${escapeHtml(s.label)}</small></button>`;
        })
        .join("")}
    </div>`;
}

async function loadEmojiAndStickerCatalog() {
  if (msgEmojiLoaded) return;
  const emojiPanel = document.getElementById("msg-emoji-panel");
  const stickerPanel = document.getElementById("msg-sticker-panel");
  if (emojiPanel) emojiPanel.innerHTML = `<div class="msg-emoji-empty">Loading emoji…</div>`;
  if (stickerPanel) stickerPanel.innerHTML = `<div class="msg-emoji-empty">Loading stickers…</div>`;
  try {
    const [emojiData, stickerData] = await Promise.all([
      api("/api/emojis?limit=180"),
      api("/api/stickers/packs"),
    ]);
    msgEmojiCatalog = emojiData.emojis || [];
    if (Array.isArray(emojiData.quick_reactions) && emojiData.quick_reactions.length) {
      MSG_QUICK_REACTIONS.splice(0, MSG_QUICK_REACTIONS.length, ...emojiData.quick_reactions);
    }
    msgStickerPacks = stickerData.packs || [];
    msgActiveStickerPackId = msgStickerPacks[0]?.id || "";
    renderEmojiPanelItems(msgEmojiCatalog);
    renderStickerPackTabs();
    renderActiveStickerPack();
    msgEmojiLoaded = true;
  } catch (err) {
    if (emojiPanel) emojiPanel.innerHTML = `<div class="msg-emoji-empty">${escapeHtml(err.message)}</div>`;
    if (stickerPanel) stickerPanel.innerHTML = `<div class="msg-emoji-empty">Could not load stickers</div>`;
  }
}

async function searchEmojiCatalog(query) {
  const q = query.trim();
  if (!q) {
    renderEmojiPanelItems(msgEmojiCatalog);
    return;
  }
  try {
    const data = await api(`/api/emojis?q=${encodeURIComponent(q)}&limit=100`);
    renderEmojiPanelItems(data.emojis || []);
  } catch {
    const filtered = msgEmojiCatalog.filter((e) => {
      const hay = `${e.name || ""} ${e.slug || ""} ${e.char || ""}`.toLowerCase();
      return hay.includes(q.toLowerCase());
    });
    renderEmojiPanelItems(filtered);
  }
}

function setEmojiPickerTab(tab = "emoji") {
  const picker = document.getElementById("msg-emoji-picker");
  const search = document.getElementById("msg-emoji-search");
  const packTabs = document.getElementById("msg-sticker-pack-tabs");
  if (!picker) return;
  picker.querySelectorAll(".msg-emoji-tab").forEach((btn) => {
    const active = btn.dataset.emojiTab === tab;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });
  picker.querySelectorAll(".msg-emoji-panel").forEach((panel) => {
    panel.hidden = panel.dataset.emojiPanel !== tab;
  });
  if (search) {
    search.hidden = tab !== "emoji";
    search.placeholder = "Search emoji…";
  }
  if (packTabs) packTabs.hidden = tab !== "stickers";
}

function closeEmojiPicker() {
  const picker = document.getElementById("msg-emoji-picker");
  const btn = document.getElementById("msg-attach-emoji");
  if (picker) picker.hidden = true;
  if (btn) {
    btn.classList.remove("is-open");
    btn.setAttribute("aria-expanded", "false");
  }
}

async function toggleEmojiPicker() {
  const picker = document.getElementById("msg-emoji-picker");
  const btn = document.getElementById("msg-attach-emoji");
  if (!picker) return;
  const open = picker.hidden;
  if (open) {
    picker.hidden = false;
    btn?.classList.add("is-open");
    btn?.setAttribute("aria-expanded", "true");
    setEmojiPickerTab("emoji");
    await loadEmojiAndStickerCatalog();
  } else {
    closeEmojiPicker();
  }
}

function insertComposeEmoji(emoji) {
  const input = document.getElementById("msg-compose-input");
  if (!input || !emoji) return;
  const start = input.selectionStart ?? input.value.length;
  const end = input.selectionEnd ?? input.value.length;
  const before = input.value.slice(0, start);
  const after = input.value.slice(end);
  const next = `${before}${emoji}${after}`.slice(0, 2000);
  input.value = next;
  const caret = Math.min(start + emoji.length, next.length);
  input.focus();
  input.setSelectionRange(caret, caret);
  resizeComposeInput();
}

async function sendStickerMessage({ packId = "", stickerId = "", emoji = "" } = {}) {
  if (!requireLogin("send a sticker")) return;
  if (!msgActiveConversationId || !emoji) return;
  const text = encodeStickerMessage({ packId, stickerId, emoji });
  try {
    await api(`/api/messages/conversations/${encodeURIComponent(msgActiveConversationId)}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, text }),
    });
    closeEmojiPicker();
    await refreshActiveChat({ forceScroll: true });
    await loadConversationList();
  } catch (err) {
    showToast(err.message, true);
  }
}

function renderMessageReactions(reactions = []) {
  const chips = (reactions || [])
    .map(
      (r) =>
        `<button type="button" class="msg-reaction-chip${r.reacted ? " is-mine" : ""}" data-reaction-emoji="${escapeAttr(r.emoji)}" title="${escapeAttr(r.emoji)}">${escapeHtml(r.emoji)}<span>${r.count}</span></button>`
    )
    .join("");
  const quick = MSG_QUICK_REACTIONS.map(
    (emoji) =>
      `<button type="button" class="msg-react-quick" data-reaction-emoji="${escapeAttr(emoji)}" title="React ${escapeAttr(emoji)}" aria-label="React with ${escapeAttr(emoji)}">${emoji}</button>`
  ).join("");
  return `<div class="msg-reaction-bar" hidden>${quick}</div>
    ${chips ? `<div class="msg-reactions">${chips}</div>` : `<div class="msg-reactions" hidden></div>`}`;
}

async function toggleMessageReaction(messageId, emoji) {
  if (!requireLogin("react to a message")) return;
  if (!msgActiveConversationId || !messageId || !emoji) return;
  try {
    await api(
      `/api/messages/conversations/${encodeURIComponent(msgActiveConversationId)}/messages/${encodeURIComponent(messageId)}/reactions`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, emoji }),
      }
    );
    msgLastThreadKey = "";
    await refreshActiveChat({ forceScroll: false });
  } catch (err) {
    showToast(err.message, true);
  }
}

function renderConversationList(conversations) {
  const list = document.getElementById("msg-conversation-list");
  if (!list) return;
  if (!conversations.length) {
    list.innerHTML = `<div class="msg-empty">
      <strong>No chats yet</strong>
      <span>Search above to message another cook.</span>
    </div>`;
    return;
  }
  list.innerHTML = conversations
    .map((c) => {
      const other = c.other_user || {};
      const name = peerDisplayName(other);
      const handle = peerHandle(other) || (other.username ? `@${other.username}` : "");
      const avatar = other.avatar_url
        ? `<img src="${escapeAttr(other.avatar_url)}" alt="" />`
        : profileInitials(name);
      const active = c.conversation_id === msgActiveConversationId ? " active" : "";
      const unreadClass = c.unread_count > 0 ? " unread" : "";
      const unread =
        c.unread_count > 0
          ? `<span class="msg-unread-badge">${c.unread_count > 99 ? "99+" : c.unread_count}</span>`
          : "";
      const preview = formatMsgPreviewText(c.last_message_preview || "");
      return `<button type="button" class="msg-conversation-item${active}${unreadClass}" data-conversation-id="${escapeAttr(c.conversation_id)}" data-user-id="${escapeAttr(other.user_id || "")}" data-username="${escapeAttr(other.username || name)}" data-display-name="${escapeAttr(name)}" data-avatar-url="${escapeAttr(other.avatar_url || "")}">
        <span class="msg-avatar">${avatar}</span>
        <span class="msg-conversation-body">
          <span class="msg-conversation-top"><strong>${escapeHtml(name)}</strong>${unread}<span class="msg-conversation-time">${escapeHtml(formatMsgListTime(c.last_message_at))}</span></span>
          <span class="msg-conversation-preview">${handle ? `<span class="msg-handle">${escapeHtml(handle)}</span> · ` : ""}${escapeHtml(preview)}</span>
        </span>
      </button>`;
    })
    .join("");
}

function renderMessageThread(messages, { forceScroll = false } = {}) {
  const thread = document.getElementById("msg-thread");
  if (!thread) return;
  const key = messages
    .map((m) => {
      const reacts = (m.reactions || []).map((r) => `${r.emoji}:${r.count}:${r.reacted ? 1 : 0}`).join(",");
      return `${m.message_id}:${reacts}`;
    })
    .join("|");
  const stickToBottom = forceScroll || isThreadNearBottom(thread);
  if (key === msgLastThreadKey && thread.childElementCount) return;
  msgLastThreadKey = key;

  if (!messages.length) {
    thread.innerHTML = `<div class="msg-empty msg-thread-empty">
      <strong>Say hello</strong>
      <span>Send the first message to start this chat.</span>
    </div>`;
    return;
  }

  let lastDay = "";
  let lastMine = null;
  const parts = [];
  messages.forEach((m, i) => {
    const day = msgDayKey(m.created_at);
    if (day && day !== lastDay) {
      lastDay = day;
      parts.push(`<div class="msg-day-sep"><span>${escapeHtml(formatMsgDayLabel(m.created_at))}</span></div>`);
      lastMine = null;
    }
    const clustered = lastMine === m.mine;
    lastMine = m.mine;
    const next = messages[i + 1];
    const nextSame = next && next.mine === m.mine && msgDayKey(next.created_at) === day;
    const deleteBtn = m.mine
      ? `<button type="button" class="msg-delete-btn" data-message-id="${escapeAttr(m.message_id)}" title="Delete message" aria-label="Delete message">×</button>`
      : "";
    const sticker = parseStickerMessage(m.text);
    const emojiOnly = !sticker && !(m.media_type && m.media_type !== "text") && isEmojiOnlyMessage(m.text);
    let body;
    let extraClass = "";
    if (sticker) {
      const visual = sticker.imageUrl
        ? `<img class="msg-sticker-img" src="${escapeAttr(sticker.imageUrl)}" alt="${escapeAttr(sticker.emoji)}" loading="lazy" />`
        : `<span class="msg-sticker" role="img" aria-label="Sticker">${escapeHtml(sticker.emoji)}</span>`;
      body = visual;
      extraClass = " msg-bubble-sticker";
    } else if (emojiOnly) {
      body = `<p class="msg-emoji-only">${escapeHtml(m.text)}</p>`;
      extraClass = " msg-bubble-emoji";
    } else {
      body = `${renderMessageMedia(m)}${m.text ? `<p>${escapeHtml(m.text)}</p>` : ""}`;
    }
    const hasReactions = (m.reactions || []).length > 0;
    parts.push(`<div class="msg-bubble${m.mine ? " mine" : ""}${clustered ? " clustered" : ""}${nextSame ? " has-next" : ""}${m.media_type && m.media_type !== "text" ? " has-media" : ""}${extraClass}${hasReactions ? " has-reactions" : ""}" data-message-id="${escapeAttr(m.message_id)}">
        ${deleteBtn}
        <button type="button" class="msg-react-btn" data-message-id="${escapeAttr(m.message_id)}" title="React" aria-label="Add reaction">+</button>
        ${body}
        ${renderMessageReactions(m.reactions || [])}
        <time datetime="${escapeAttr(m.created_at || "")}">${escapeHtml(formatMsgBubbleTime(m.created_at))}</time>
      </div>`);
  });
  thread.innerHTML = parts.join("");
  enhanceVoicePlayers(thread);
  if (stickToBottom) thread.scrollTop = thread.scrollHeight;
}

function formatVoiceDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "";
  const total = Math.round(seconds);
  const m = Math.floor(total / 60);
  const s = String(total % 60).padStart(2, "0");
  return `${m}:${s}`;
}

function enhanceVoicePlayers(root) {
  root?.querySelectorAll(".msg-media-voice").forEach((wrap) => {
    const audio = wrap.querySelector("audio");
    const durationEl = wrap.querySelector(".msg-voice-duration");
    if (!audio) return;
    const markReady = () => {
      if (!Number.isFinite(audio.duration) || audio.duration === Infinity) return;
      wrap.classList.remove("is-loading");
      wrap.classList.add("is-ready");
      if (durationEl) {
        durationEl.hidden = false;
        durationEl.textContent = formatVoiceDuration(audio.duration);
      }
    };
    audio.addEventListener("loadedmetadata", markReady);
    audio.addEventListener("durationchange", markReady);
    if (audio.readyState >= 1) markReady();
  });
}

function formatFileSize(bytes) {
  const n = Number(bytes) || 0;
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function renderMessageMedia(m) {
  const type = m.media_type || "text";
  const url = m.media_url;
  if (!url || type === "text") return "";
  if (type === "image") {
    return `<a class="msg-media-link" href="${escapeAttr(url)}" target="_blank" rel="noopener"><img class="msg-media-image" src="${escapeAttr(url)}" alt="${escapeAttr(m.file_name || "Photo")}" loading="lazy" /></a>`;
  }
  if (type === "video") {
    return `<video class="msg-media-video" src="${escapeAttr(url)}" controls playsinline preload="metadata"></video>`;
  }
  if (type === "voice") {
    return `<div class="msg-media-voice is-loading">
      <div class="msg-voice-skeleton" aria-hidden="true"><span></span><span></span><span></span></div>
      <audio controls preload="metadata" src="${escapeAttr(url)}"></audio>
      <span class="msg-voice-duration" hidden></span>
    </div>`;
  }
  const name = m.file_name || "Document";
  const size = m.file_size ? ` · ${formatFileSize(m.file_size)}` : "";
  return `<a class="msg-media-doc" href="${escapeAttr(url)}" target="_blank" rel="noopener" download="${escapeAttr(name)}">
      <span class="msg-media-doc-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3.5h6.2L18.5 8v12.5a1.5 1.5 0 0 1-1.5 1.5H8A1.5 1.5 0 0 1 6.5 20.5v-15A2 2 0 0 1 8 3.5z"/><path d="M14 3.5V8h4.5"/></svg>
      </span>
      <span class="msg-media-doc-meta"><strong>${escapeHtml(name)}</strong><span>${escapeHtml(size.trim() || "Document")}</span></span>
    </a>`;
}

function clearMsgAttachment() {
  msgPendingFile = null;
  msgPendingKind = null;
  if (msgPendingPreviewUrl) {
    URL.revokeObjectURL(msgPendingPreviewUrl);
    msgPendingPreviewUrl = null;
  }
  const preview = document.getElementById("msg-attach-preview");
  if (preview) {
    preview.hidden = true;
    preview.innerHTML = "";
  }
  ["msg-file-image", "msg-file-video", "msg-file-doc"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
}

function setMsgAttachment(file, kind) {
  if (!file) return;
  clearMsgAttachment();
  msgPendingFile = file;
  msgPendingKind = kind;
  msgPendingPreviewUrl = URL.createObjectURL(file);
  const preview = document.getElementById("msg-attach-preview");
  if (!preview) return;
  preview.hidden = false;
  let body = "";
  if (kind === "image") {
    body = `<img src="${escapeAttr(msgPendingPreviewUrl)}" alt="" />`;
  } else if (kind === "video") {
    body = `<video src="${escapeAttr(msgPendingPreviewUrl)}" muted></video>`;
  } else if (kind === "voice") {
    body = `<audio src="${escapeAttr(msgPendingPreviewUrl)}" controls></audio>`;
  } else {
    body = `<div class="msg-attach-doc-chip"><strong>${escapeHtml(file.name)}</strong><span>${escapeHtml(formatFileSize(file.size))}</span></div>`;
  }
  preview.innerHTML = `${body}<button type="button" class="msg-attach-remove" id="msg-attach-remove" aria-label="Remove attachment">×</button>`;
  document.getElementById("msg-attach-remove")?.addEventListener("click", clearMsgAttachment);
}

function stopVoiceTracks() {
  if (msgVoiceStream) {
    msgVoiceStream.getTracks().forEach((t) => t.stop());
    msgVoiceStream = null;
  }
}

function setVoiceBtnRecording(active) {
  const voiceBtn = document.getElementById("msg-attach-voice");
  if (!voiceBtn) return;
  voiceBtn.classList.toggle("recording", !!active);
  voiceBtn.title = active ? "Stop & send voice" : "Record voice";
  voiceBtn.setAttribute("aria-label", active ? "Stop and send voice message" : "Record voice");
}

function cancelVoiceRecording({ silent = false } = {}) {
  if (msgVoiceTimer) clearInterval(msgVoiceTimer);
  msgVoiceTimer = null;
  if (msgVoiceRecorder && msgVoiceRecorder.state !== "inactive") {
    try {
      msgVoiceRecorder.ondataavailable = null;
      msgVoiceRecorder.onstop = null;
      msgVoiceRecorder.stop();
    } catch {
      /* ignore */
    }
  }
  msgVoiceRecorder = null;
  msgVoiceChunks = [];
  stopVoiceTracks();
  setVoiceBtnRecording(false);
}

async function startVoiceRecording() {
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
    showToast("Voice recording is not supported in this browser", true);
    return;
  }
  if (msgVoiceRecorder) {
    cancelVoiceRecording({ silent: true });
  }
  try {
    msgVoiceStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mime = MediaRecorder.isTypeSupported("audio/webm")
      ? "audio/webm"
      : MediaRecorder.isTypeSupported("audio/ogg")
        ? "audio/ogg"
        : "";
    msgVoiceChunks = [];
    const recorder = mime ? new MediaRecorder(msgVoiceStream, { mimeType: mime }) : new MediaRecorder(msgVoiceStream);
    msgVoiceRecorder = recorder;
    recorder.ondataavailable = (e) => {
      if (e.data?.size) msgVoiceChunks.push(e.data);
    };
    recorder.onstop = async () => {
      const blobType = recorder.mimeType || mime || "audio/webm";
      const chunks = msgVoiceChunks.slice();
      msgVoiceChunks = [];
      msgVoiceRecorder = null;
      stopVoiceTracks();
      setVoiceBtnRecording(false);
      if (msgVoiceTimer) clearInterval(msgVoiceTimer);
      msgVoiceTimer = null;
      const blob = new Blob(chunks, { type: blobType });
      if (!blob.size) {
        showToast("No audio captured", true);
        return;
      }
      const ext = blobType.includes("ogg") ? "ogg" : "webm";
      const file = new File([blob], `voice-${Date.now()}.${ext}`, { type: blobType });
      await sendChatMedia(file, "voice");
    };
    recorder.start();
    msgVoiceStartedAt = Date.now();
    setVoiceBtnRecording(true);
    msgVoiceTimer = setInterval(() => {
      if (Date.now() - msgVoiceStartedAt > 120000 && msgVoiceRecorder?.state === "recording") {
        msgVoiceRecorder.stop();
      }
    }, 500);
  } catch (err) {
    stopVoiceTracks();
    setVoiceBtnRecording(false);
    showToast(err.message || "Microphone permission denied", true);
  }
}

function stopVoiceRecordingAndSend() {
  if (!msgVoiceRecorder || msgVoiceRecorder.state !== "recording") return;
  msgVoiceRecorder.stop();
}

async function sendChatMedia(file, kind) {
  if (!userId || !msgActiveConversationId || !file) return;
  const input = document.getElementById("msg-compose-input");
  const caption = input?.value.trim() || "";
  const sendBtn = document.getElementById("msg-send-btn");
  if (sendBtn) sendBtn.disabled = true;
  const fd = new FormData();
  fd.append("user_id", userId);
  fd.append("text", caption);
  fd.append("kind", kind);
  fd.append("file", file, file.name);
  try {
    const res = await fetch(
      `/api/messages/conversations/${encodeURIComponent(msgActiveConversationId)}/media`,
      { method: "POST", body: fd }
    );
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data.detail;
      throw new Error(Array.isArray(detail) ? detail.map((d) => d.msg || String(d)).join(", ") : detail || "Upload failed");
    }
    if (input) {
      input.value = "";
      resizeComposeInput();
    }
    clearMsgAttachment();
    msgLastThreadKey = "";
    await refreshActiveChat({ forceScroll: true });
    await loadConversationList();
  } catch (err) {
    showToast(err.message, true);
  } finally {
    if (sendBtn) sendBtn.disabled = false;
    input?.focus();
  }
}

async function deleteChatMessage(messageId) {
  if (!userId || !msgActiveConversationId || !messageId) return;
  const ok = await askConfirm("This removes the message from the chat.", {
    title: "Delete message?",
    okLabel: "Delete",
  });
  if (!ok) return;
  try {
    await api(
      `/api/messages/conversations/${encodeURIComponent(msgActiveConversationId)}/messages/${encodeURIComponent(messageId)}?user_id=${encodeURIComponent(userId)}`,
      { method: "DELETE" }
    );
    msgLastThreadKey = "";
    await refreshActiveChat({ forceScroll: false });
    await loadConversationList();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function deleteActiveChat() {
  if (!userId || !msgActiveConversationId) return;
  const name = msgActivePeer?.username || "this chat";
  const ok = await askConfirm(
    `This permanently removes the chat with ${name} and all messages for both of you. This cannot be undone.`,
    { title: "Delete conversation?", okLabel: "Delete chat" }
  );
  if (!ok) return;
  const conversationId = msgActiveConversationId;
  try {
    await api(
      `/api/messages/conversations/${encodeURIComponent(conversationId)}?user_id=${encodeURIComponent(userId)}`,
      { method: "DELETE" }
    );
    closeActiveConversation();
    await loadConversationList();
    await loadMsgUnreadBadge();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function refreshActiveChat({ forceScroll = false } = {}) {
  if (!msgActiveConversationId || !userId) return;
  try {
    const data = await api(
      `/api/messages/conversations/${encodeURIComponent(msgActiveConversationId)}/messages?user_id=${encodeURIComponent(userId)}&limit=100`
    );
    renderMessageThread(data.messages || [], { forceScroll });
    await api(`/api/messages/conversations/${encodeURIComponent(msgActiveConversationId)}/read`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId }),
    });
    loadMsgUnreadBadge();
  } catch (err) {
    setStatus(document.getElementById("messages-status"), err.message, true);
  }
}

async function openConversation(conversationId, peer = {}) {
  if (!conversationId) return;
  msgActiveConversationId = conversationId;
  msgLastThreadKey = "";
  document.getElementById("messages-chat-empty").hidden = true;
  document.getElementById("messages-chat-active").hidden = false;
  setMessagesChatOpen(true);
  setChatPeerHeader(peer);
  document.querySelectorAll(".msg-conversation-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.conversationId === conversationId);
  });
  const thread = document.getElementById("msg-thread");
  if (thread) thread.innerHTML = `<div class="msg-empty">Loading chat…</div>`;
  await refreshActiveChat({ forceScroll: true });
  stopMessageThreadPolling();
  msgPollTimer = setInterval(() => refreshActiveChat(), 4000);
  const input = document.getElementById("msg-compose-input");
  if (input) {
    input.value = "";
    resizeComposeInput();
    input.focus();
  }
}

function closeActiveConversation() {
  stopMessageThreadPolling();
  msgActiveConversationId = null;
  msgActivePeer = null;
  msgLastThreadKey = "";
  clearMsgAttachment();
  cancelVoiceRecording({ silent: true });
  closeEmojiPicker();
  setMessagesChatOpen(false);
  const empty = document.getElementById("messages-chat-empty");
  const active = document.getElementById("messages-chat-active");
  if (empty) empty.hidden = false;
  if (active) active.hidden = true;
  document.querySelectorAll(".msg-conversation-item.active").forEach((el) => el.classList.remove("active"));
}

async function openDirectChatWithUser(otherUserId) {
  if (!requireLogin("send messages")) return;
  if (!otherUserId || otherUserId === userId) return;
  try {
    const data = await api("/api/messages/conversations/direct", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, other_user_id: otherUserId }),
    });
    showPanel("messages");
    await loadMessagesPanel();
    const conv = data.conversation;
    const other = conv.other_user || {};
    await openConversation(conv.conversation_id, {
      user_id: other.user_id,
      username: other.username || "Chat",
      display_name: other.display_name || other.username || "Chat",
      avatar_url: other.avatar_url || "",
    });
  } catch (err) {
    showToast(err.message, true);
  }
}

async function sendChatMessage(e) {
  e.preventDefault();
  if (!userId || !msgActiveConversationId) return;
  if (msgPendingFile && msgPendingKind) {
    await sendChatMedia(msgPendingFile, msgPendingKind);
    return;
  }
  const input = document.getElementById("msg-compose-input");
  const text = input?.value.trim();
  if (!text) return;
  const sendBtn = document.getElementById("msg-send-btn");
  if (sendBtn) sendBtn.disabled = true;
  if (input) {
    input.value = "";
    resizeComposeInput();
  }
  try {
    await api(`/api/messages/conversations/${encodeURIComponent(msgActiveConversationId)}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, text }),
    });
    await refreshActiveChat({ forceScroll: true });
    await loadConversationList();
  } catch (err) {
    if (input) {
      input.value = text;
      resizeComposeInput();
    }
    showToast(err.message, true);
  } finally {
    if (sendBtn) sendBtn.disabled = false;
    input?.focus();
  }
}

async function loadConversationList() {
  if (!userId) return;
  const data = await api(`/api/messages/conversations?user_id=${encodeURIComponent(userId)}`);
  renderConversationList(data.conversations || []);
}

async function searchUsersForMessage(query) {
  const resultsEl = document.getElementById("msg-user-results");
  const clearBtn = document.getElementById("msg-search-clear");
  if (!resultsEl) return;
  const q = query.trim();
  if (clearBtn) clearBtn.hidden = !q;
  if (q.length < 2) {
    resultsEl.hidden = true;
    resultsEl.innerHTML = "";
    return;
  }
  resultsEl.hidden = false;
  resultsEl.innerHTML = `<div class="msg-empty">Searching…</div>`;
  try {
    const data = await api(`/api/users/search?q=${encodeURIComponent(q)}&viewer_id=${encodeURIComponent(userId)}`);
    const users = (data.users || []).filter((u) => u.user_id !== userId);
    if (!users.length) {
      resultsEl.innerHTML = `<div class="msg-empty">No users found for “${escapeHtml(q)}”.</div>`;
      return;
    }
    resultsEl.innerHTML = users
      .map((u) => {
        const name = peerDisplayName(u);
        const avatar = u.avatar_url
          ? `<img src="${escapeAttr(u.avatar_url)}" alt="" />`
          : profileInitials(name);
        return `<button type="button" class="msg-user-result" data-user-id="${escapeAttr(u.user_id)}">
          <span class="msg-avatar">${avatar}</span>
          <span class="msg-user-result-meta">
            <strong>${escapeHtml(name)}</strong>
            <span class="muted">${u.username ? `@${escapeHtml(u.username)} · ` : ""}Message</span>
          </span>
        </button>`;
      })
      .join("");
  } catch (err) {
    resultsEl.innerHTML = `<div class="msg-empty">${escapeHtml(err.message)}</div>`;
  }
}

async function loadMessagesPanel() {
  const statusEl = document.getElementById("messages-status");
  if (!userId) {
    setMessagesVisibility(false);
    closeActiveConversation();
    setStatus(statusEl, "");
    return;
  }
  setMessagesVisibility(true);
  if (!mongoAvailable) {
    setStatus(statusEl, "Connect MongoDB to use messages.", true);
    return;
  }
  loadEmojiAndStickerCatalog().catch(() => {});
  const list = document.getElementById("msg-conversation-list");
  if (list && !list.childElementCount) {
    list.innerHTML = `<div class="msg-empty">Loading conversations…</div>`;
  }
  setStatus(statusEl, "");
  try {
    await loadConversationList();
    await loadMsgUnreadBadge();
    if (msgActiveConversationId) {
      setMessagesChatOpen(true);
      await refreshActiveChat();
    } else {
      setMessagesChatOpen(false);
    }
  } catch (err) {
    setStatus(statusEl, err.message, true);
  }
}

function initMessages() {
  document.getElementById("messages-login-btn")?.addEventListener("click", () => openAuthDialog("login"));
  document.getElementById("msg-compose-form")?.addEventListener("submit", sendChatMessage);
  document.getElementById("msg-back-btn")?.addEventListener("click", closeActiveConversation);
  document.getElementById("msg-delete-chat-btn")?.addEventListener("click", deleteActiveChat);
  document.getElementById("msg-attach-emoji")?.addEventListener("click", (e) => {
    e.stopPropagation();
    toggleEmojiPicker();
  });
  document.getElementById("msg-emoji-search")?.addEventListener("input", (e) => {
    clearTimeout(msgEmojiSearchTimer);
    msgEmojiSearchTimer = setTimeout(() => searchEmojiCatalog(e.target.value || ""), 220);
  });
  document.getElementById("msg-emoji-picker")?.addEventListener("click", (e) => {
    const tab = e.target.closest(".msg-emoji-tab");
    if (tab) {
      setEmojiPickerTab(tab.dataset.emojiTab || "emoji");
      return;
    }
    const packTab = e.target.closest(".msg-sticker-pack-tab");
    if (packTab) {
      msgActiveStickerPackId = packTab.dataset.packId || "";
      renderStickerPackTabs();
      renderActiveStickerPack();
      return;
    }
    const emojiBtn = e.target.closest(".msg-emoji-item");
    if (emojiBtn) {
      insertComposeEmoji(emojiBtn.dataset.emoji || "");
      return;
    }
    const stickerBtn = e.target.closest(".msg-sticker-item");
    if (stickerBtn) {
      sendStickerMessage({
        packId: stickerBtn.dataset.packId || "",
        stickerId: stickerBtn.dataset.stickerId || "",
        emoji: stickerBtn.dataset.sticker || "",
      });
    }
  });
  document.addEventListener("click", (e) => {
    if (e.target.closest("#msg-emoji-picker") || e.target.closest("#msg-attach-emoji")) return;
    closeEmojiPicker();
    document.querySelectorAll(".msg-bubble.is-reacting").forEach((el) => el.classList.remove("is-reacting"));
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeEmojiPicker();
      document.querySelectorAll(".msg-bubble.is-reacting").forEach((el) => el.classList.remove("is-reacting"));
    }
  });
  document.getElementById("msg-attach-image")?.addEventListener("click", () => {
    closeEmojiPicker();
    document.getElementById("msg-file-image")?.click();
  });
  document.getElementById("msg-attach-video")?.addEventListener("click", () => {
    closeEmojiPicker();
    document.getElementById("msg-file-video")?.click();
  });
  document.getElementById("msg-attach-doc")?.addEventListener("click", () => {
    closeEmojiPicker();
    document.getElementById("msg-file-doc")?.click();
  });
  document.getElementById("msg-attach-voice")?.addEventListener("click", () => {
    closeEmojiPicker();
    if (msgVoiceRecorder?.state === "recording") stopVoiceRecordingAndSend();
    else startVoiceRecording();
  });
  document.getElementById("msg-file-image")?.addEventListener("change", (e) => {
    const file = e.target.files?.[0];
    if (file) setMsgAttachment(file, "image");
  });
  document.getElementById("msg-file-video")?.addEventListener("change", (e) => {
    const file = e.target.files?.[0];
    if (file) setMsgAttachment(file, "video");
  });
  document.getElementById("msg-file-doc")?.addEventListener("change", (e) => {
    const file = e.target.files?.[0];
    if (file) setMsgAttachment(file, "document");
  });
  document.getElementById("msg-chat-peer")?.addEventListener("click", () => {
    const id = document.getElementById("msg-chat-peer")?.dataset.userId;
    if (id) viewUserProfile(id);
  });
  document.getElementById("msg-thread")?.addEventListener("click", (e) => {
    const reactBtn = e.target.closest(".msg-react-btn");
    if (reactBtn) {
      e.preventDefault();
      e.stopPropagation();
      const bubble = reactBtn.closest(".msg-bubble");
      document.querySelectorAll(".msg-bubble.is-reacting").forEach((el) => {
        if (el !== bubble) el.classList.remove("is-reacting");
      });
      bubble?.classList.toggle("is-reacting");
      return;
    }
    const reaction = e.target.closest(".msg-react-quick, .msg-reaction-chip");
    if (reaction) {
      e.preventDefault();
      e.stopPropagation();
      const bubble = reaction.closest(".msg-bubble");
      const messageId = bubble?.dataset.messageId || "";
      const emoji = reaction.dataset.reactionEmoji || "";
      bubble?.classList.remove("is-reacting");
      toggleMessageReaction(messageId, emoji);
      return;
    }
    const btn = e.target.closest(".msg-delete-btn");
    if (!btn) return;
    e.preventDefault();
    deleteChatMessage(btn.dataset.messageId);
  });
  document.getElementById("msg-conversation-list")?.addEventListener("click", (e) => {
    const item = e.target.closest(".msg-conversation-item");
    if (!item) return;
    openConversation(item.dataset.conversationId, {
      user_id: item.dataset.userId || "",
      username: item.dataset.username || "Chat",
      display_name: item.dataset.displayName || item.dataset.username || "Chat",
      avatar_url: item.dataset.avatarUrl || "",
    });
  });

  const searchInput = document.getElementById("msg-user-search");
  const clearBtn = document.getElementById("msg-search-clear");
  searchInput?.addEventListener("input", () => {
    clearTimeout(msgUserSearchTimer);
    if (clearBtn) clearBtn.hidden = !searchInput.value.trim();
    msgUserSearchTimer = setTimeout(() => searchUsersForMessage(searchInput.value), 280);
  });
  searchInput?.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeMessageSearch();
  });
  clearBtn?.addEventListener("click", () => {
    closeMessageSearch();
    searchInput?.focus();
  });
  document.getElementById("msg-user-results")?.addEventListener("click", async (e) => {
    const row = e.target.closest(".msg-user-result");
    if (!row) return;
    closeMessageSearch();
    await openDirectChatWithUser(row.dataset.userId);
  });
  document.addEventListener("click", (e) => {
    const wrap = e.target.closest(".msg-search-wrap");
    if (!wrap) {
      const resultsEl = document.getElementById("msg-user-results");
      if (resultsEl && !resultsEl.hidden) {
        resultsEl.hidden = true;
      }
    }
  });

  const compose = document.getElementById("msg-compose-input");
  compose?.addEventListener("input", resizeComposeInput);
  compose?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      document.getElementById("msg-compose-form")?.requestSubmit();
    }
  });
}

async function boot() {
  initTheme();
  initHeaderScroll();
  initNav();
  initAuth();
  setupVoice();
  initMatchForm();
  initFridgeFeatures();
  initMealPlan();
  initSurplus();
  initRestaurants();
  initPosts();
  initMessages();
  initNotifications();
  initUserSearch();
  initRecipeDialog();
  initProfileLists();
  renderIngredientPills();
  updateAuthUi();
  await checkHealth();
  await refreshSession();
  if (userId) profileViewUserId = userId;
  updateAuthUi();
  if (userId && mongoAvailable) {
    pollFridgeAlerts();
    startNotificationPolling();
    startMessageUnreadPolling();
    loadNotifications();
    loadMsgUnreadBadge();
  }
  const activePanel = location.hash.slice(1) || "pantry";
  if (activePanel === "pantry") loadPantry();
  if (activePanel === "meal-plan") loadMealPlanPanel();
  if (activePanel === "posts") loadPosts();
  if (activePanel === "restaurants") loadRestaurantsPanel();
  if (activePanel === "messages") loadMessagesPanel();
  if (activePanel === "profile") loadProfile();
  if (activePanel === "admin") loadAdmin();
  document.body.classList.add("page-ready");
}

boot();
