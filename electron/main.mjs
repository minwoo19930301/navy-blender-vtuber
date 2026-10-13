// navy-blender-vtuber — macOS·Windows 데스크톱 오버레이 셸
// 공통 레시피: transparent + frame:false + screen-saver level + setIgnoreMouseEvents(forward) + 렌더러 히트테스트 토글
// macOS 추가: type:'panel' + visibleOnFullScreen (풀스크린 앱 위에도 뜸)
// Windows 추가: backgroundColor '#00000000', 작업 표시줄 버튼 + 트레이 아이콘 (창에 프레임이 없어 메뉴 막대가 안 보인다)
import { app, BrowserWindow, ipcMain, screen, globalShortcut, session, Menu, Tray, systemPreferences, dialog, shell } from 'electron'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { existsSync, writeFileSync } from 'node:fs'

const __dirname = dirname(fileURLToPath(import.meta.url))

const isMac = process.platform === 'darwin'
const isWin = process.platform === 'win32'
/** 단축키 안내 문구용 — 같은 키(Alt)를 맥에서는 Option이라 부른다 */
const ALT_NAME = isMac ? 'Option' : 'Alt'

// Windows: 작업 표시줄 그룹·알림이 이 앱으로 묶이게 (패키징된 exe는 이 ID를 쓴다)
if (isWin) app.setAppUserModelId('com.minwokim.navy-blender-vtuber')

// 공 몸통 + 국수 팔: 양팔을 옆으로 뻗으면 공 지름의 약 2.3배라 가로세로 비슷한 창
const WIN_W = 300 // 기본 창 크기 (예전 600×700 의 절반 — 화면을 덜 가리게)
const WIN_H = 350

/** @type {BrowserWindow | null} */
let win = null
let cursorTimer = null
/** @type {Tray | null} */
let tray = null

/** Windows 아이콘(.ico): 패키징된 앱은 electron/icon.ico, 저장소에서 실행하면 build/icon.ico */
function windowsIconPath() {
  for (const p of [join(__dirname, 'icon.ico'), join(__dirname, '../build/icon.ico')]) if (existsSync(p)) return p
  return undefined
}

function sendDebug(cmd) {
  if (win && !win.isDestroyed()) win.webContents.send('mingo:debug-cmd', cmd)
}

function toggleVisible() {
  if (win) win.isVisible() ? win.hide() : win.show()
}

/**
 * 숫자키 리액션 [id, 이름, 숫자키] (id 는 렌더러 src/reactions 와 같다). 단축키는 Ctrl+Option(맥)/Ctrl+Alt(Windows)+숫자 — 다른 앱에 포커스가 있어도 먹는 전역 단축키다.
 * 10번 '일하는 척' 은 자판의 0 키다. 취소는 Ctrl+Alt+Esc (렌더러 창에 포커스가 있으면 Esc 만으로도 된다)
 */
const REACTIONS = [
  [1, '웃음', '1'], [2, '사랑', '2'], [3, '인사', '3'], [4, '놀람', '4'], [5, '감동', '5'], [6, '뽀뽀', '6'], [7, '화남', '7'], [8, '졸림', '8'], [9, '축하', '9'],
  [10, '일하는 척', '0'],
]
const CANCEL_KEY = 'Control+Alt+Escape'

function sendReaction(cmd) {
  // 숨겨진 동안(카메라·렌더 루프 정지)에는 보내지 않는다 — 다시 보일 때 옛 리액션이 갑자기 재생되지 않게
  if (win && !win.isDestroyed() && win.isVisible()) sendDebug(cmd)
}

/**
 * 메뉴 바와 우클릭 팝업이 공유하는 리액션 항목. 단축키는 전역 등록(globalShortcut)이 처리하므로
 * 메뉴에는 표시만 하고 따로 등록하지 않는다 (registerAccelerator: false, 같은 키가 두 번 발동하지 않게).
 */
function reactionMenuItems() {
  return [
    ...REACTIONS.map(([n, name, key]) => ({
      label: `${key}  ${name}`,
      accelerator: `Control+Alt+${key}`, // Alt == Option (맥) — 한 표기로 두 OS에서 같은 키
      registerAccelerator: false,
      click: () => sendReaction(`reaction-${n}`),
    })),
    { type: 'separator' },
    { label: '리액션 취소', accelerator: CANCEL_KEY, registerAccelerator: false, click: () => sendReaction('reaction-cancel') },
  ]
}

/** 메뉴 바와 우클릭 팝업이 공유하는 보기 옵션 */
function viewMenuItems() {
  return [
    { label: '아바타 작게', accelerator: 'CommandOrControl+Shift+-', click: () => sendDebug('avatar-smaller') },
    { label: '아바타 크게', accelerator: 'CommandOrControl+Shift+=', click: () => sendDebug('avatar-larger') },
    { label: '아바타 크기 리셋', accelerator: 'CommandOrControl+Shift+0', click: () => sendDebug('avatar-reset') },
    { type: 'separator' },
    { label: '배경: 투명 / 크로마키 그린 / 단색', accelerator: 'CommandOrControl+Shift+B', click: () => sendDebug('bg-cycle') },
    { label: '좌우 미러 반전 (팔이 반대로 움직일 때)', accelerator: 'CommandOrControl+Shift+X', click: () => sendDebug('mirror-toggle') },
    { label: '트래킹 디버그 오버레이', accelerator: 'CommandOrControl+Shift+D', click: () => sendDebug('debug-toggle') },
  ]
}

function popupOptionsMenu() {
  if (!win || win.isDestroyed()) return
  const menu = Menu.buildFromTemplate([
    { label: '리액션', submenu: reactionMenuItems() },
    { type: 'separator' },
    ...viewMenuItems(),
    { type: 'separator' },
    { label: '네이비 숨기기/보이기', accelerator: 'CommandOrControl+Shift+M', click: toggleVisible },
    { role: 'reload' },
    { type: 'separator' },
    { label: '종료', accelerator: 'CommandOrControl+Q', click: () => app.quit() },
  ])
  menu.popup({ window: win })
}

function createWindow() {
  const { workArea } = screen.getPrimaryDisplay()
  const windowIcon = isWin ? windowsIconPath() : undefined

  win = new BrowserWindow({
    width: WIN_W,
    height: WIN_H,
    x: workArea.x + workArea.width - WIN_W - 24,
    y: workArea.y + workArea.height - WIN_H - 8,
    transparent: true,
    frame: false,
    hasShadow: false,
    ...(isMac
      ? { type: 'panel' } // NSPanel: 풀스크린 앱 위에도 뜸 (electron#36364 회피)
      : {
          backgroundColor: '#00000000', // Windows: 완전 투명 (없으면 합성 단계에서 흰/검은 배경이 비칠 수 있다)
          skipTaskbar: false, // 프레임 없는 창이라 작업 표시줄 버튼이 찾을 단서다
          ...(windowIcon ? { icon: windowIcon } : {}),
        }),
    // Electron 문서: 투명 창은 크기 조절이 안 되고, resizable:true 가 투명을 깨뜨릴 수 있다. 맥은 지금 그대로 둔다.
    // Windows는 창 크기를 고정한다 (이동은 아래 drag-by IPC, 아바타 크기는 메뉴의 줌으로 조절).
    resizable: isMac,
    minWidth: 180,
    minHeight: 200,
    fullscreenable: false,
    webPreferences: {
      preload: join(__dirname, 'preload.cjs'),
      backgroundThrottling: false,
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  win.setAlwaysOnTop(true, 'screen-saver')
  if (isMac) {
    win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })
    if (win.setHiddenInMissionControl) win.setHiddenInMissionControl(true)
  }
  // 기본은 클릭스루 ON — 렌더러가 아바타 위에서만 OFF로 토글
  win.setIgnoreMouseEvents(true, { forward: true })

  // NAVY_SMOKE_SHOT=경로.png: 카메라 없이(nocam) 띄워 창을 캡처하고 종료 — 패키징 전 셸 검증용
  const smokeShot = process.env.NAVY_SMOKE_SHOT
  const query = smokeShot ? { nocam: '1' } : undefined
  const devServer = process.env.VITE_DEV_SERVER
  if (devServer) win.loadURL(devServer + '/index.html' + (smokeShot ? '?nocam=1' : ''))
  else win.loadFile(join(__dirname, '../dist/index.html'), { query })
  if (smokeShot) {
    win.webContents.once('did-finish-load', () => {
      setTimeout(async () => {
        if (!win || win.isDestroyed()) return
        const img = await win.webContents.capturePage()
        writeFileSync(smokeShot, img.toPNG())
        console.log(`[navy] smoke shot → ${smokeShot} (${img.getSize().width}x${img.getSize().height})`)
        app.quit()
      }, Number(process.env.NAVY_SMOKE_DELAY ?? 2500)) // 모델(GLB)·얼굴 준비가 늦으면 NAVY_SMOKE_DELAY 로 늘린다
    })
  }

  // backgroundThrottling:false면 hide 후에도 renderer의 visibilityState가 'visible'로
  // 남아 visibilitychange가 발화하지 않는다 (Electron 문서화 동작).
  // → hide/show를 명시적 IPC로 방송해 renderer가 렌더 루프·웹캠·MediaPipe를 멈추게 한다.
  win.on('hide', () => { if (win && !win.isDestroyed()) win.webContents.send('mingo:visibility', false) })
  win.on('show', () => { if (win && !win.isDestroyed()) win.webContents.send('mingo:visibility', true) })

  // 전역 커서 방송 (시선 추적 + 히트테스트용) — 30Hz
  cursorTimer = setInterval(() => {
    if (!win || win.isDestroyed() || !win.isVisible()) return
    const p = screen.getCursorScreenPoint()
    const b = win.getBounds()
    const d = screen.getPrimaryDisplay()
    win.webContents.send('mingo:cursor', {
      sx: p.x, sy: p.y,
      wx: p.x - b.x, wy: p.y - b.y,
      inWindow: p.x >= b.x && p.x < b.x + b.width && p.y >= b.y && p.y < b.y + b.height,
      winW: b.width, winH: b.height,
      screenW: d.size.width, screenH: d.size.height,
    })
  }, 33)
}

/**
 * Windows 카메라 권한. Windows에는 앱별 권한 창이 없고 "설정 > 개인 정보 및 보안 > 카메라"의 전역 스위치
 * ("카메라 액세스", "데스크톱 앱이 카메라에 액세스하도록 허용")만 있다. 꺼져 있으면 getUserMedia가
 * NotAllowedError/NotReadableError로 실패하므로, 'denied'로 읽힐 때만 미리 안내한다 (모르겠으면 조용히 통과 —
 * 그때는 렌더러가 getUserMedia 실패를 보고 토스트로 알려 준다).
 */
async function ensureCameraAccessWindows() {
  let status = 'unknown'
  try {
    status = systemPreferences.getMediaAccessStatus('camera')
  } catch {
    return
  }
  if (status !== 'denied') return
  const { response } = await dialog.showMessageBox({
    type: 'warning',
    message: '네이비가 카메라를 쓸 수 없습니다',
    detail: 'Windows 설정 > 개인 정보 및 보안 > 카메라에서 "카메라 액세스"와 "데스크톱 앱이 카메라에 액세스하도록 허용"을 켠 뒤 다시 실행해 주세요. 카메라 없이도 idle 동작과 리액션은 됩니다.',
    buttons: ['카메라 설정 열기', '닫기'],
    defaultId: 0,
  })
  if (response === 0) void shell.openExternal('ms-settings:privacy-webcam')
}

/**
 * macOS 카메라 권한(TCC). Electron은 Chromium과 달리 OS 권한 창을 스스로 띄우지 않는다 —
 * 상태가 not-determined면 getUserMedia가 트랙은 주지만 프레임이 0인 채로 멈춘다(실측).
 * 창을 만들기 전에 한 번 묻고, 거부돼 있으면 시스템 설정으로 안내한다.
 */
async function ensureCameraAccess() {
  if (isWin) return ensureCameraAccessWindows()
  if (!isMac) return
  const status = systemPreferences.getMediaAccessStatus('camera')
  if (status === 'granted') return
  if (status === 'not-determined') {
    const ok = await systemPreferences.askForMediaAccess('camera')
    console.log(`[navy] camera access ${ok ? 'granted' : 'denied'}`)
    if (ok) return
  }
  const { response } = await dialog.showMessageBox({
    type: 'warning',
    message: '네이비가 카메라를 쓸 수 없습니다',
    detail: '시스템 설정 > 개인정보 보호 및 보안 > 카메라에서 이 앱(또는 실행한 터미널)을 켠 뒤 다시 실행해 주세요. 카메라 없이도 idle 동작과 리액션은 됩니다.',
    buttons: ['카메라 설정 열기', '닫기'],
    defaultId: 0,
  })
  if (response === 0) void shell.openExternal('x-apple.systempreferences:com.apple.preference.security?Privacy_Camera')
}

/**
 * Windows 트레이 아이콘. 창에 프레임이 없고 hide()하면 작업 표시줄 버튼도 사라져서,
 * 숨긴 네이비를 되살리는 눈에 보이는 길이 필요하다 (전역 단축키 말고도).
 * 왼쪽 클릭은 숨기기/보이기, 오른쪽 클릭은 메뉴.
 */
function createTray() {
  if (!isWin) return
  const iconPath = windowsIconPath()
  if (!iconPath) return
  tray = new Tray(iconPath)
  tray.setToolTip('Navy Blender VTuber')
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: '네이비 숨기기/보이기', click: toggleVisible },
    { type: 'separator' },
    { label: '종료', click: () => app.quit() },
  ]))
  tray.on('click', toggleVisible)
}

app.whenReady().then(async () => {
  // 렌더러의 media 요청은 허용 (OS 권한은 아래 ensureCameraAccess가 담당)
  session.defaultSession.setPermissionRequestHandler((_wc, permission, cb) => {
    cb(permission === 'media')
  })
  if (!process.env.NAVY_SMOKE_SHOT) await ensureCameraAccess()

  Menu.setApplicationMenu(Menu.buildFromTemplate([
    {
      label: 'Navy',
      submenu: [
        { label: '네이비 숨기기/보이기', accelerator: 'CommandOrControl+Shift+M', click: toggleVisible },
        { role: 'reload' },
        { role: 'toggleDevTools' }, // 주의: 투명창은 detached 모드로만
        { type: 'separator' },
        { label: 'Navy 종료', accelerator: 'CommandOrControl+Q', click: () => app.quit() },
      ],
    },
    { label: '리액션', submenu: reactionMenuItems() },
    { label: '보기', submenu: viewMenuItems() },
  ]))

  createWindow()
  createTray()

  // 방송 화면공유 대비 퀵 하이드 (setContentProtection은 macOS 15+에서 무력)
  globalShortcut.register('CommandOrControl+Shift+M', toggleVisible)

  // 숫자키 리액션: Ctrl+Option(Alt)+1..9, 0(일하는 척) 재생, +Esc 취소 (전역 — 다른 앱을 쓰는 중에도 먹는다)
  const taken = []
  for (const [n, , key] of REACTIONS) {
    if (!globalShortcut.register(`Control+Alt+${key}`, () => sendReaction(`reaction-${n}`))) taken.push(`Ctrl+${ALT_NAME}+${key}`)
  }
  if (!globalShortcut.register(CANCEL_KEY, () => sendReaction('reaction-cancel'))) taken.push(`Ctrl+${ALT_NAME}+Esc`)
  if (taken.length > 0) console.warn(`[navy] 전역 단축키를 못 잡았습니다 (다른 앱이 쓰는 중): ${taken.join(', ')}`)
})

ipcMain.on('mingo:click-through', (_e, enabled) => {
  if (!win) return
  win.setIgnoreMouseEvents(!!enabled, { forward: true })
})

ipcMain.on('mingo:drag-by', (_e, dx, dy) => {
  if (!win) return
  const b = win.getBounds()
  // Windows(배율 125·150%)는 getBounds→setBounds 왕복마다 DIP↔픽셀 반올림으로 창 크기가 조금씩 변한다.
  // 크기 조절이 없는 Windows에서는 만들 때의 크기를 그대로 넘겨 이동만 하게 한다.
  const size = isMac ? { width: b.width, height: b.height } : { width: WIN_W, height: WIN_H }
  win.setBounds({ x: Math.round(b.x + dx), y: Math.round(b.y + dy), ...size })
})

// 렌더러 우클릭 → 옵션 메뉴
ipcMain.on('mingo:options-menu', () => popupOptionsMenu())

ipcMain.on('mingo:quit', () => app.quit())

app.on('will-quit', () => {
  if (cursorTimer) clearInterval(cursorTimer)
  globalShortcut.unregisterAll()
  tray?.destroy() // 안 지우면 Windows 트레이에 죽은 아이콘이 남는다
})

app.on('window-all-closed', () => app.quit())
