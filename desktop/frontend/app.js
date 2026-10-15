const state = {
  results: [],
  anime: [],
  reminders: [],
  filter: "all",
  busy: false,
  reminderAnimeId: null
}

const statusLabels = {
  watching: "正在追",
  paused: "已暂停",
  finished: "已看完"
}

const dayLabels = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]

const els = {
  keyword: document.querySelector("#keywordInput"),
  headed: document.querySelector("#headedInput"),
  search: document.querySelector("#searchBtn"),
  refresh: document.querySelector("#refreshBtn"),
  manualAdd: document.querySelector("#manualAddBtn"),
  status: document.querySelector("#statusText"),
  resultsSection: document.querySelector("#resultsSection"),
  resultList: document.querySelector("#resultList"),
  animeList: document.querySelector("#animeList"),
  reminderList: document.querySelector("#reminderList"),
  resultCount: document.querySelector("#resultCount"),
  animeCount: document.querySelector("#animeCount"),
  reminderCount: document.querySelector("#reminderCount"),
  watchingStat: document.querySelector("#watchingStat"),
  finishedStat: document.querySelector("#finishedStat"),
  reminderStat: document.querySelector("#reminderStat"),
  template: document.querySelector("#animeCardTemplate"),
  reminderDialog: document.querySelector("#reminderDialog"),
  reminderForm: document.querySelector("#reminderForm"),
  reminderTitle: document.querySelector("#reminderAnimeTitle"),
  reminderEnabled: document.querySelector("#reminderEnabledInput"),
  broadcastDay: document.querySelector("#broadcastDayInput"),
  broadcastTime: document.querySelector("#broadcastTimeInput"),
  reminderMinutes: document.querySelector("#reminderMinutesInput"),
  manualDialog: document.querySelector("#manualDialog"),
  manualForm: document.querySelector("#manualForm"),
  manualTitle: document.querySelector("#manualTitleInput"),
  manualTotal: document.querySelector("#manualTotalInput"),
  manualWatched: document.querySelector("#manualWatchedInput"),
  manualUrl: document.querySelector("#manualUrlInput")
}

els.search.addEventListener("click", searchXifan)
els.refresh.addEventListener("click", () => refreshAll())
els.manualAdd.addEventListener("click", openManualDialog)
els.keyword.addEventListener("keydown", event => {
  if (event.key === "Enter") searchXifan()
})
els.reminderForm.addEventListener("submit", saveReminder)
els.manualForm.addEventListener("submit", saveManualAnime)

document.querySelectorAll("[data-filter]").forEach(button => {
  button.addEventListener("click", () => {
    state.filter = button.dataset.filter
    document.querySelectorAll("[data-filter]").forEach(item => {
      item.classList.toggle("active", item === button)
    })
    renderAnime()
  })
})

document.querySelectorAll("[data-close-dialog]").forEach(button => {
  button.addEventListener("click", () => button.closest("dialog").close())
})

refreshAll({ initial: true })

async function loadData() {
  const [anime, reminders] = await Promise.all([
    requestJson("/api/anime"),
    requestJson("/api/reminders/today")
  ])
  state.anime = anime || []
  state.reminders = reminders || []
  renderDashboard()
}

async function refreshAll(options = {}) {
  setBusy(true)
  if (!options.initial) setStatus("正在刷新数据…")
  try {
    await loadData()
    setStatus(options.initial ? "数据已载入。" : "数据已刷新。", "success")
  } catch (error) {
    setStatus(`刷新失败：${error.message}`, "error")
  } finally {
    setBusy(false)
  }
}

async function searchXifan() {
  const keyword = els.keyword.value.trim()
  if (!keyword) {
    setStatus("请先输入番剧名称。", "error")
    els.keyword.focus()
    return
  }

  setBusy(true)
  setStatus(els.headed.checked ? "正在打开浏览器并搜索…" : "正在从稀饭动漫搜索…")
  try {
    const params = new URLSearchParams({
      q: keyword,
      limit: "8",
      headed: String(els.headed.checked)
    })
    const data = await requestJson(`/api/crawlers/xifan/search?${params}`)
    state.results = data.results || []
    renderResults()
    setStatus(
      state.results.length ? `找到 ${state.results.length} 条结果。` : "没有找到匹配结果，可以尝试别名或手动添加。",
      state.results.length ? "success" : ""
    )
    els.resultsSection.scrollIntoView({ behavior: "smooth", block: "start" })
  } catch (error) {
    state.results = []
    renderResults()
    setStatus(`搜索失败：${error.message}`, "error")
  } finally {
    setBusy(false)
  }
}

async function importAnime(item) {
  setBusy(true)
  setStatus(`正在加入：${item.title}`)
  try {
    await requestJson("/api/crawlers/xifan/import", {
      method: "POST",
      body: JSON.stringify(item),
      headers: { "Content-Type": "application/json" }
    })
    await loadData()
    setStatus(`已加入追番：${item.title}`, "success")
  } catch (error) {
    setStatus(`加入失败：${error.message}`, "error")
  } finally {
    setBusy(false)
  }
}

async function updateProgress(item, next) {
  const watched = Math.max(0, next)
  if (item.total_episodes !== null && watched > item.total_episodes) return

  setBusy(true)
  try {
    await requestJson(`/api/anime/${item.id}/progress`, {
      method: "POST",
      body: JSON.stringify({ watched_episodes: watched }),
      headers: { "Content-Type": "application/json" }
    })
    await loadData()
    setStatus(`进度已更新：${item.title}`, "success")
  } catch (error) {
    setStatus(`更新失败：${error.message}`, "error")
  } finally {
    setBusy(false)
  }
}

async function updateStatus(item, status) {
  setBusy(true)
  try {
    await patchAnime(item.id, { status })
    await loadData()
    setStatus(`${item.title}：${statusLabels[status]}`, "success")
  } catch (error) {
    setStatus(`状态更新失败：${error.message}`, "error")
  } finally {
    setBusy(false)
  }
}

async function deleteAnime(item) {
  if (!confirm(`确定从追番列表移除“${item.title}”吗？`)) return
  setBusy(true)
  try {
    await requestJson(`/api/anime/${item.id}`, { method: "DELETE" })
    await loadData()
    setStatus(`已移除：${item.title}`, "success")
  } catch (error) {
    setStatus(`移除失败：${error.message}`, "error")
  } finally {
    setBusy(false)
  }
}

async function markReminded(item) {
  setBusy(true)
  try {
    await requestJson(`/api/anime/${item.id}/reminded`, { method: "POST" })
    await loadData()
    setStatus(`已确认今日提醒：${item.title}`, "success")
  } catch (error) {
    setStatus(`操作失败：${error.message}`, "error")
  } finally {
    setBusy(false)
  }
}

function openReminderDialog(item) {
  state.reminderAnimeId = item.id
  els.reminderTitle.textContent = item.title
  els.reminderEnabled.checked = Boolean(item.reminder_enabled)
  els.broadcastDay.value = item.broadcast_day === null ? "" : String(item.broadcast_day)
  els.broadcastTime.value = item.broadcast_time || "20:00"
  els.reminderMinutes.value = String(item.reminder_minutes ?? 15)
  els.reminderDialog.showModal()
}

async function saveReminder(event) {
  event.preventDefault()
  const dayValue = els.broadcastDay.value
  if (els.reminderEnabled.checked && dayValue === "") {
    setStatus("启用提醒前，请选择每周更新日。", "error")
    els.broadcastDay.focus()
    return
  }

  setBusy(true)
  try {
    await patchAnime(state.reminderAnimeId, {
      reminder_enabled: els.reminderEnabled.checked,
      broadcast_day: dayValue === "" ? null : Number(dayValue),
      broadcast_time: els.broadcastTime.value,
      reminder_minutes: Number(els.reminderMinutes.value)
    })
    els.reminderDialog.close()
    await loadData()
    setStatus("提醒设置已保存。", "success")
  } catch (error) {
    setStatus(`保存失败：${error.message}`, "error")
  } finally {
    setBusy(false)
  }
}

function openManualDialog() {
  els.manualForm.reset()
  els.manualWatched.value = "0"
  els.manualDialog.showModal()
  els.manualTitle.focus()
}

async function saveManualAnime(event) {
  event.preventDefault()
  const watched = Number(els.manualWatched.value || 0)
  const total = els.manualTotal.value === "" ? null : Number(els.manualTotal.value)
  if (total !== null && watched > total) {
    setStatus("当前进度不能超过总集数。", "error")
    els.manualWatched.focus()
    return
  }

  setBusy(true)
  try {
    await requestJson("/api/anime", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: els.manualTitle.value.trim(),
        total_episodes: total,
        watched_episodes: watched,
        play_url: els.manualUrl.value.trim() || null,
        reminder_enabled: false
      })
    })
    els.manualDialog.close()
    await loadData()
    setStatus("番剧已手动添加。", "success")
  } catch (error) {
    setStatus(`添加失败：${error.message}`, "error")
  } finally {
    setBusy(false)
  }
}

function patchAnime(id, payload) {
  return requestJson(`/api/anime/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  })
}

function renderDashboard() {
  renderStats()
  renderAnime()
  renderReminders()
  if (!els.resultsSection.hidden) renderResults()
}

function renderStats() {
  els.watchingStat.textContent = state.anime.filter(item => item.status === "watching").length
  els.finishedStat.textContent = state.anime.filter(item => item.status === "finished").length
  els.reminderStat.textContent = state.reminders.length
}

function renderResults() {
  els.resultsSection.hidden = false
  els.resultCount.textContent = `${state.results.length} 部`
  renderList(els.resultList, state.results, "search", "没有搜索结果。")
}

function renderAnime() {
  const items = state.filter === "all"
    ? state.anime
    : state.anime.filter(item => item.status === state.filter)
  els.animeCount.textContent = state.filter === "all"
    ? `${items.length} 部`
    : `${items.length} / ${state.anime.length} 部`
  renderList(els.animeList, items, "watchlist", "这里还没有番剧，试试搜索或手动添加。")
}

function renderReminders() {
  els.reminderCount.textContent = `${state.reminders.length} 部`
  renderList(els.reminderList, state.reminders, "reminder", "今天暂时没有到点的更新提醒。")
}

function renderList(root, items, mode, emptyText) {
  root.replaceChildren()
  if (!items.length) {
    const empty = document.createElement("p")
    empty.className = "empty"
    empty.textContent = emptyText
    root.append(empty)
    return
  }

  items.forEach(item => root.append(createCard(item, mode)))
}

function createCard(item, mode) {
  const node = els.template.content.firstElementChild.cloneNode(true)
  const title = node.querySelector("h3")
  const poster = node.querySelector(".poster")
  const score = node.querySelector(".score")
  const badges = node.querySelector(".badges")
  const meta = node.querySelector(".meta")
  const summary = node.querySelector(".summary")
  const actions = node.querySelector(".actions")

  title.textContent = item.title || "未命名番剧"
  if (item.cover_url) {
    poster.src = item.cover_url
    poster.alt = `${item.title} 封面`
    poster.referrerPolicy = "no-referrer"
    poster.addEventListener("error", () => poster.remove())
  } else {
    poster.remove()
  }
  score.textContent = item.score !== null && item.score !== undefined ? item.score.toFixed(1) : ""
  addBadges(badges, item, mode)
  meta.textContent = buildMeta(item, mode)
  summary.textContent = item.summary || (mode === "search" ? "暂无简介。" : "还没有简介，可从搜索结果重新导入以更新资料。")

  if (mode !== "search") renderProgress(node, item)
  appendExternalLinks(actions, item)
  appendActions(actions, item, mode)
  return node
}

function addBadges(root, item, mode) {
  if (mode !== "search" && item.status) {
    root.append(badge(statusLabels[item.status] || item.status, item.status))
  }
  if (mode === "search" && item.status_text) root.append(badge(item.status_text))
  if (item.year) root.append(badge(String(item.year)))
  if (item.source === "xifan") root.append(badge("稀饭动漫"))
}

function badge(text, className = "") {
  const element = document.createElement("span")
  element.className = `badge ${className}`.trim()
  element.textContent = text
  return element
}

function renderProgress(node, item) {
  const wrap = node.querySelector(".progress-wrap")
  const value = Number(item.watched_episodes || 0)
  const total = item.total_episodes
  wrap.hidden = false
  wrap.querySelector("strong").textContent = total === null ? `${value} 集` : `${value} / ${total}`
  const percent = total ? Math.min(100, Math.round(value / total * 100)) : Math.min(100, value * 5)
  wrap.querySelector(".progress-track span").style.width = `${percent}%`
}

function buildMeta(item, mode) {
  const parts = []
  if (mode !== "search" && item.source_status) parts.push(item.source_status)
  if (mode === "search" && item.total_episodes) parts.push(`共 ${item.total_episodes} 集`)
  if (mode !== "search" && item.reminder_enabled && item.broadcast_day !== null) {
    parts.push(`${dayLabels[item.broadcast_day]} ${item.broadcast_time} 提醒`)
  }
  if (item.tags) {
    const tags = Array.isArray(item.tags) ? item.tags : item.tags.split(",")
    parts.push(tags.filter(Boolean).slice(0, 3).join(" / "))
  }
  return parts.filter(Boolean).join(" · ") || "暂无补充信息"
}

function appendExternalLinks(root, item) {
  if (item.source_url) root.append(linkButton("详情", item.source_url))
  if (item.play_url && item.play_url !== item.source_url) root.append(linkButton("去观看", item.play_url))
}

function appendActions(root, item, mode) {
  if (mode === "search") {
    const tracked = state.anime.some(anime => (
      anime.source === item.source && anime.source_id && anime.source_id === item.source_id
    ))
    const button = actionButton(tracked ? "已在列表" : "加入追番", () => importAnime(item), "primary")
    button.disabled = tracked
    root.append(button)
    return
  }

  if (mode === "reminder") {
    root.append(actionButton("今天已提醒", () => markReminded(item), "primary"))
    return
  }

  const watched = Number(item.watched_episodes || 0)
  const atEnd = item.total_episodes !== null && watched >= item.total_episodes
  const minus = actionButton("−1 集", () => updateProgress(item, watched - 1))
  minus.disabled = watched <= 0
  const plus = actionButton("+1 集", () => updateProgress(item, watched + 1), "primary")
  plus.disabled = atEnd
  root.append(minus, plus)

  if (item.status === "finished") {
    root.append(actionButton("继续追", () => updateStatus(item, "watching")))
  } else {
    root.append(actionButton(item.status === "paused" ? "继续追" : "暂停", () => {
      updateStatus(item, item.status === "paused" ? "watching" : "paused")
    }))
    root.append(actionButton("标记看完", () => updateStatus(item, "finished")))
  }
  root.append(actionButton("提醒设置", () => openReminderDialog(item)))
  root.append(actionButton("移除", () => deleteAnime(item), "danger"))
}

function actionButton(text, handler, className = "") {
  const button = document.createElement("button")
  button.type = "button"
  button.className = className
  button.textContent = text
  button.addEventListener("click", handler)
  return button
}

function linkButton(text, href) {
  const link = document.createElement("a")
  link.href = href
  link.target = "_blank"
  link.rel = "noreferrer"
  link.textContent = text
  return link
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options)
  if (response.status === 204) return null

  const contentType = response.headers.get("content-type") || ""
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text()
  if (!response.ok) {
    const message = typeof payload === "object" ? payload.detail : payload
    throw new Error(message || `HTTP ${response.status}`)
  }
  return payload
}

function setBusy(isBusy) {
  state.busy = isBusy
  els.search.disabled = isBusy
  els.refresh.disabled = isBusy
  els.manualAdd.disabled = isBusy
  document.querySelectorAll(".actions button").forEach(button => {
    if (isBusy && !button.disabled) {
      button.dataset.disabledByBusy = "true"
      button.disabled = true
    } else if (!isBusy && button.dataset.disabledByBusy) {
      delete button.dataset.disabledByBusy
      button.disabled = false
    }
  })
}

function setStatus(text, tone = "") {
  els.status.textContent = text
  if (tone) els.status.dataset.tone = tone
  else delete els.status.dataset.tone
}
