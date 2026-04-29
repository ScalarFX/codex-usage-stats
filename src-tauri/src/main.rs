#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use chrono::{DateTime, Datelike, Duration, Local, NaiveDate, Utc};
use chrono_tz::Tz;
use once_cell::sync::Lazy;
use serde::Serialize;
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::env;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::str::FromStr;
use std::sync::Mutex;
use std::time::{Duration as StdDuration, Instant};
use tauri::{
    AppHandle,
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, Runtime, WebviewWindow, WindowEvent,
};
use walkdir::WalkDir;

const CACHE_TTL: StdDuration = StdDuration::from_secs(30);

static CACHE: Lazy<Mutex<Option<SessionCache>>> = Lazy::new(|| Mutex::new(None));

#[derive(Clone)]
struct SessionCache {
    codex_home: PathBuf,
    sessions_dir: PathBuf,
    sessions_dir_exists: bool,
    loaded_at: Instant,
    sessions: Vec<SessionSummary>,
}

#[derive(Clone, Default)]
struct TokenUsage {
    input_tokens: u64,
    cached_input_tokens: u64,
    output_tokens: u64,
    reasoning_output_tokens: u64,
    total_tokens: u64,
}

impl TokenUsage {
    fn non_cached_input_tokens(&self) -> u64 {
        self.input_tokens.saturating_sub(self.cached_input_tokens)
    }

    fn effective_tokens(&self) -> u64 {
        self.non_cached_input_tokens()
            .saturating_add(self.output_tokens)
    }
}

#[derive(Clone)]
struct SessionSummary {
    start: DateTime<Utc>,
    duration_s: f64,
    timezone_name: String,
    models: Vec<String>,
    usage: TokenUsage,
}

#[derive(Serialize)]
struct StatsResponse {
    range: String,
    timezone: String,
    totals: Totals,
    trend: Vec<TrendPoint>,
    heatmap: Heatmap,
    codex_home: String,
    sessions_dir: String,
    sessions_dir_exists: bool,
}

#[derive(Serialize)]
struct Totals {
    effective_tokens: u64,
    raw_total_tokens: u64,
    total_tokens: u64,
    input_tokens: u64,
    non_cached_input_tokens: u64,
    cached_input_tokens: u64,
    output_tokens: u64,
    reasoning_output_tokens: u64,
    duration_s: f64,
    session_count: usize,
    active_days: usize,
    top_model: String,
    models: BTreeMap<String, u64>,
}

#[derive(Serialize)]
struct TrendPoint {
    date: String,
    effective_tokens: u64,
    tokens: u64,
    sessions: u64,
}

#[derive(Serialize)]
struct Heatmap {
    start: String,
    end: String,
    weeks: u32,
    effective_tokens_by_day: BTreeMap<String, u64>,
    tokens_by_day: BTreeMap<String, u64>,
}

struct TrayUsage {
    today: u64,
    seven_days: u64,
    thirty_days: u64,
}

enum ResolvedTz {
    Named(Tz),
    Local,
}

impl ResolvedTz {
    fn today(&self) -> NaiveDate {
        match self {
            ResolvedTz::Named(tz) => Utc::now().with_timezone(tz).date_naive(),
            ResolvedTz::Local => Local::now().date_naive(),
        }
    }

    fn date_for(&self, dt: DateTime<Utc>) -> NaiveDate {
        match self {
            ResolvedTz::Named(tz) => dt.with_timezone(tz).date_naive(),
            ResolvedTz::Local => dt.with_timezone(&Local).date_naive(),
        }
    }
}

#[tauri::command]
fn get_stats(
    app: AppHandle,
    range: String,
    refresh: Option<bool>,
    codex_home: Option<String>,
) -> Result<StatsResponse, String> {
    let cache = load_sessions(codex_home.as_deref(), refresh.unwrap_or(false))?;
    let response = aggregate(&cache.sessions, &range, &cache);
    update_tray_usage(&app, &cache.sessions, cache.sessions_dir_exists);
    Ok(response)
}

fn load_sessions(codex_home_arg: Option<&str>, refresh: bool) -> Result<SessionCache, String> {
    let codex_home = codex_home_arg
        .filter(|s| !s.trim().is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(default_codex_home);
    let sessions_dir = codex_home.join("sessions");

    if !refresh {
        if let Some(hit) = cache_hit(&codex_home) {
            return Ok(hit);
        }
    }

    let sessions_dir_exists = sessions_dir.exists();
    let sessions = if sessions_dir_exists {
        parse_all(&sessions_dir)?
    } else {
        Vec::new()
    };

    let cache = SessionCache {
        codex_home,
        sessions_dir,
        sessions_dir_exists,
        loaded_at: Instant::now(),
        sessions,
    };

    *CACHE
        .lock()
        .map_err(|_| "缓存锁定失败".to_string())? = Some(cache.clone());

    Ok(cache)
}

fn cache_hit(codex_home: &Path) -> Option<SessionCache> {
    let guard = CACHE.lock().ok()?;
    let cache = guard.as_ref()?;
    if cache.codex_home == codex_home && cache.loaded_at.elapsed() <= CACHE_TTL {
        Some(cache.clone())
    } else {
        None
    }
}

fn default_codex_home() -> PathBuf {
    env::var_os("CODEX_HOME")
        .map(PathBuf::from)
        .or_else(|| env::var_os("USERPROFILE").map(|h| PathBuf::from(h).join(".codex")))
        .or_else(|| {
            let drive = env::var_os("HOMEDRIVE")?;
            let path = env::var_os("HOMEPATH")?;
            Some(PathBuf::from(format!(
                "{}{}",
                drive.to_string_lossy(),
                path.to_string_lossy()
            ))
            .join(".codex"))
        })
        .unwrap_or_else(|| PathBuf::from(".codex"))
}

fn parse_all(sessions_root: &Path) -> Result<Vec<SessionSummary>, String> {
    let mut sessions = Vec::new();
    for entry in WalkDir::new(sessions_root).into_iter().filter_map(Result::ok) {
        let path = entry.path();
        if !entry.file_type().is_file() || !is_rollout(path) {
            continue;
        }
        if let Some(session) = parse_rollout(path) {
            sessions.push(session);
        }
    }
    sessions.sort_by_key(|s| s.start);
    Ok(sessions)
}

fn is_rollout(path: &Path) -> bool {
    let name = path.file_name().and_then(|s| s.to_str()).unwrap_or("");
    name.starts_with("rollout-") && name.ends_with(".jsonl")
}

fn parse_rollout(path: &Path) -> Option<SessionSummary> {
    let file = File::open(path).ok()?;
    let reader = BufReader::new(file);
    let mut meta: Option<Value> = None;
    let mut last_ts: Option<DateTime<Utc>> = None;
    let mut models = Vec::new();
    let mut timezone_name = String::new();
    let mut usage = TokenUsage::default();

    for line in reader.lines().map_while(Result::ok) {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let obj: Value = match serde_json::from_str(line) {
            Ok(v) => v,
            Err(_) => continue,
        };
        if let Some(ts) = obj.get("timestamp").and_then(Value::as_str) {
            if let Some(parsed) = parse_ts(ts) {
                last_ts = Some(parsed);
            }
        }

        let item_type = obj.get("type").and_then(Value::as_str).unwrap_or("");
        let payload = obj.get("payload").unwrap_or(&Value::Null);
        match item_type {
            "session_meta" => meta = Some(payload.clone()),
            "turn_context" => {
                if let Some(model) = payload.get("model").and_then(Value::as_str) {
                    models.push(model.to_string());
                }
                if timezone_name.is_empty() {
                    if let Some(tz) = payload.get("timezone").and_then(Value::as_str) {
                        timezone_name = tz.to_string();
                    }
                }
            }
            "event_msg" => {
                if payload.get("type").and_then(Value::as_str) == Some("token_count") {
                    if let Some(total) = payload
                        .get("info")
                        .and_then(|v| v.get("total_token_usage"))
                    {
                        usage = token_usage_from_value(total);
                    }
                }
            }
            _ => {}
        }
    }

    let meta = meta?;
    let start = meta
        .get("timestamp")
        .and_then(Value::as_str)
        .and_then(parse_ts)?;
    let end = last_ts.unwrap_or(start);
    let duration_s = (end - start).num_milliseconds().max(0) as f64 / 1000.0;

    Some(SessionSummary {
        start,
        duration_s,
        timezone_name,
        models,
        usage,
    })
}

fn parse_ts(value: &str) -> Option<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(value)
        .ok()
        .map(|dt| dt.with_timezone(&Utc))
}

fn token_usage_from_value(value: &Value) -> TokenUsage {
    TokenUsage {
        input_tokens: json_u64(value, "input_tokens"),
        cached_input_tokens: json_u64(value, "cached_input_tokens"),
        output_tokens: json_u64(value, "output_tokens"),
        reasoning_output_tokens: json_u64(value, "reasoning_output_tokens"),
        total_tokens: json_u64(value, "total_tokens"),
    }
}

fn json_u64(value: &Value, key: &str) -> u64 {
    value.get(key).and_then(Value::as_u64).unwrap_or(0)
}

fn aggregate(sessions: &[SessionSummary], range: &str, cache: &SessionCache) -> StatsResponse {
    let range = match range {
        "7d" | "30d" | "all" => range.to_string(),
        _ => "all".to_string(),
    };
    let (tz, timezone_label) = resolve_tz(sessions);
    let filtered = filter_by_range(sessions, &range, &tz);

    let mut total = TokenUsage::default();
    let mut total_duration_s = 0.0;
    let mut model_counts: HashMap<String, u64> = HashMap::new();
    let mut daily_tokens: BTreeMap<String, u64> = BTreeMap::new();
    let mut daily_sessions: BTreeMap<String, u64> = BTreeMap::new();
    let mut active_days: BTreeSet<NaiveDate> = BTreeSet::new();

    for session in &filtered {
        total.input_tokens = total.input_tokens.saturating_add(session.usage.input_tokens);
        total.cached_input_tokens = total
            .cached_input_tokens
            .saturating_add(session.usage.cached_input_tokens);
        total.output_tokens = total.output_tokens.saturating_add(session.usage.output_tokens);
        total.reasoning_output_tokens = total
            .reasoning_output_tokens
            .saturating_add(session.usage.reasoning_output_tokens);
        total.total_tokens = total.total_tokens.saturating_add(session.usage.total_tokens);
        total_duration_s += session.duration_s;

        for model in &session.models {
            *model_counts.entry(model.clone()).or_insert(0) += 1;
        }

        let day = tz.date_for(session.start);
        let key = day.to_string();
        active_days.insert(day);
        *daily_tokens.entry(key.clone()).or_insert(0) += session.usage.effective_tokens();
        *daily_sessions.entry(key).or_insert(0) += 1;
    }

    let top_model = model_counts
        .iter()
        .max_by(|a, b| a.1.cmp(b.1).then_with(|| b.0.cmp(a.0)))
        .map(|(model, _)| model.clone())
        .unwrap_or_default();

    let models = model_counts.into_iter().collect::<BTreeMap<_, _>>();
    let trend = dense_daily(&daily_tokens, &daily_sessions, &range, &tz);
    let heatmap = heatmap(sessions, &tz);

    StatsResponse {
        range,
        timezone: timezone_label,
        totals: Totals {
            effective_tokens: total.effective_tokens(),
            raw_total_tokens: total.total_tokens,
            total_tokens: total.total_tokens,
            input_tokens: total.input_tokens,
            non_cached_input_tokens: total.non_cached_input_tokens(),
            cached_input_tokens: total.cached_input_tokens,
            output_tokens: total.output_tokens,
            reasoning_output_tokens: total.reasoning_output_tokens,
            duration_s: (total_duration_s * 10.0).round() / 10.0,
            session_count: filtered.len(),
            active_days: active_days.len(),
            top_model,
            models,
        },
        trend,
        heatmap,
        codex_home: cache.codex_home.display().to_string(),
        sessions_dir: cache.sessions_dir.display().to_string(),
        sessions_dir_exists: cache.sessions_dir_exists,
    }
}

fn resolve_tz(sessions: &[SessionSummary]) -> (ResolvedTz, String) {
    let mut counts: HashMap<&str, u64> = HashMap::new();
    for session in sessions {
        if !session.timezone_name.is_empty() {
            *counts.entry(&session.timezone_name).or_insert(0) += 1;
        }
    }

    if let Some((name, _)) = counts.into_iter().max_by_key(|(_, count)| *count) {
        if let Ok(tz) = Tz::from_str(name) {
            return (ResolvedTz::Named(tz), name.to_string());
        }
        return (ResolvedTz::Local, name.to_string());
    }

    (ResolvedTz::Local, Local::now().offset().to_string())
}

fn filter_by_range<'a>(
    sessions: &'a [SessionSummary],
    range: &str,
    tz: &ResolvedTz,
) -> Vec<&'a SessionSummary> {
    if range == "all" {
        return sessions.iter().collect();
    }

    let days = if range == "7d" { 7 } else { 30 };
    let cutoff = tz.today() - Duration::days(days - 1);
    sessions
        .iter()
        .filter(|s| tz.date_for(s.start) >= cutoff)
        .collect()
}

fn dense_daily(
    tokens_by_day: &BTreeMap<String, u64>,
    sessions_by_day: &BTreeMap<String, u64>,
    range: &str,
    tz: &ResolvedTz,
) -> Vec<TrendPoint> {
    let today = tz.today();
    let start = match range {
        "7d" => today - Duration::days(6),
        "30d" => today - Duration::days(29),
        _ => {
            let earliest = tokens_by_day
                .keys()
                .chain(sessions_by_day.keys())
                .filter_map(|k| NaiveDate::parse_from_str(k, "%Y-%m-%d").ok())
                .min();
            match earliest {
                Some(date) => date,
                None => return Vec::new(),
            }
        }
    };

    let mut out = Vec::new();
    let mut cur = start;
    while cur <= today {
        let key = cur.to_string();
        let tokens = tokens_by_day.get(&key).copied().unwrap_or(0);
        out.push(TrendPoint {
            date: key.clone(),
            effective_tokens: tokens,
            tokens,
            sessions: sessions_by_day.get(&key).copied().unwrap_or(0),
        });
        cur += Duration::days(1);
    }
    out
}

fn heatmap(sessions: &[SessionSummary], tz: &ResolvedTz) -> Heatmap {
    let today = tz.today();
    let weeks = 53;
    let current_week_start = today - Duration::days(today.weekday().num_days_from_sunday() as i64);
    let start = current_week_start - Duration::weeks((weeks - 1) as i64);
    let mut tokens: BTreeMap<String, u64> = BTreeMap::new();

    for session in sessions {
        let day = tz.date_for(session.start);
        if day < start || day > today {
            continue;
        }
        *tokens.entry(day.to_string()).or_insert(0) += session.usage.effective_tokens();
    }

    Heatmap {
        start: start.to_string(),
        end: today.to_string(),
        weeks,
        effective_tokens_by_day: tokens.clone(),
        tokens_by_day: tokens,
    }
}

fn tray_usage(sessions: &[SessionSummary]) -> TrayUsage {
    let (tz, _) = resolve_tz(sessions);
    let today = tz.today();
    let seven_day_start = today - Duration::days(6);
    let thirty_day_start = today - Duration::days(29);
    let mut usage = TrayUsage {
        today: 0,
        seven_days: 0,
        thirty_days: 0,
    };

    for session in sessions {
        let day = tz.date_for(session.start);
        let tokens = session.usage.effective_tokens();
        if day == today {
            usage.today = usage.today.saturating_add(tokens);
        }
        if day >= seven_day_start {
            usage.seven_days = usage.seven_days.saturating_add(tokens);
        }
        if day >= thirty_day_start {
            usage.thirty_days = usage.thirty_days.saturating_add(tokens);
        }
    }

    usage
}

fn format_tokens(n: u64) -> String {
    if n >= 1_000_000_000 {
        format!("{:.2}B", n as f64 / 1_000_000_000.0)
    } else if n >= 1_000_000 {
        format!("{:.2}M", n as f64 / 1_000_000.0)
    } else if n >= 1_000 {
        format!("{:.1}k", n as f64 / 1_000.0)
    } else {
        n.to_string()
    }
}

fn build_tray_menu<R, M>(
    manager: &M,
    usage: Option<&TrayUsage>,
    sessions_dir_exists: bool,
) -> tauri::Result<Menu<R>>
where
    R: Runtime,
    M: Manager<R>,
{
    let title = MenuItem::with_id(manager, "usage_title", "额度概览", false, None::<&str>)?;
    let today = MenuItem::with_id(
        manager,
        "usage_today",
        usage
            .map(|u| format!("今日：{} 有效 token", format_tokens(u.today)))
            .unwrap_or_else(|| "今日：等待加载".to_string()),
        false,
        None::<&str>,
    )?;
    let seven_days = MenuItem::with_id(
        manager,
        "usage_7d",
        usage
            .map(|u| format!("7 天：{} 有效 token", format_tokens(u.seven_days)))
            .unwrap_or_else(|| "7 天：等待加载".to_string()),
        false,
        None::<&str>,
    )?;
    let thirty_days = MenuItem::with_id(
        manager,
        "usage_30d",
        usage
            .map(|u| format!("30 天：{} 有效 token", format_tokens(u.thirty_days)))
            .unwrap_or_else(|| "30 天：等待加载".to_string()),
        false,
        None::<&str>,
    )?;
    let status = MenuItem::with_id(
        manager,
        "usage_status",
        if sessions_dir_exists {
            "状态：已读取本地日志"
        } else {
            "状态：找不到 sessions 目录"
        },
        false,
        None::<&str>,
    )?;
    let show_i = MenuItem::with_id(manager, "show", "显示窗口", true, None::<&str>)?;
    let quit_i = MenuItem::with_id(manager, "quit", "退出", true, None::<&str>)?;
    Menu::with_items(
        manager,
        &[
            &title,
            &today,
            &seven_days,
            &thirty_days,
            &status,
            &show_i,
            &quit_i,
        ],
    )
}

fn update_tray_usage<R: Runtime>(
    app: &AppHandle<R>,
    sessions: &[SessionSummary],
    sessions_dir_exists: bool,
) {
    let usage = tray_usage(sessions);
    let tooltip = if sessions_dir_exists {
        format!(
            "Codex 用量统计\n今日 {}\n7 天 {}\n30 天 {}",
            format_tokens(usage.today),
            format_tokens(usage.seven_days),
            format_tokens(usage.thirty_days)
        )
    } else {
        "Codex 用量统计\n找不到 sessions 目录".to_string()
    };

    if let Some(tray) = app.tray_by_id("main") {
        let _ = tray.set_tooltip(Some(tooltip));
        if let Ok(menu) = build_tray_menu(app, Some(&usage), sessions_dir_exists) {
            let _ = tray.set_menu(Some(menu));
        }
    }
}

fn show_window<R: Runtime>(window: &WebviewWindow<R>) {
    let _ = window.unminimize();
    let _ = window.show();
    let _ = window.set_focus();
}

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            let menu = build_tray_menu(app, None, true)?;

            let mut tray = TrayIconBuilder::with_id("main")
                .tooltip("Codex 用量统计")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => {
                        if let Some(window) = app.get_webview_window("main") {
                            show_window(&window);
                        }
                    }
                    "quit" => app.exit(0),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            show_window(&window);
                        }
                    }
                });

            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }

            tray.build(app)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .invoke_handler(tauri::generate_handler![get_stats])
        .run(tauri::generate_context!())
        .expect("failed to run tauri app");
}
