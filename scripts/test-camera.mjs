import test from 'node:test'
import assert from 'node:assert/strict'
import { createCameraSession } from '../src/camera.ts'

const flush = () => new Promise((resolve) => setImmediate(resolve))
const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
function fixture({ media, play, start } = {}) {
  const states = [], trackers = [], tracks = []
  const video = { srcObject: null, play: play ?? (async () => {}), pause() {} }
  const newStream = () => {
    const track = { stops: 0, stop() { this.stops++ }, addEventListener(_name, cb) { this.ended = cb } }
    tracks.push(track)
    return { getTracks: () => [track], getVideoTracks: () => [track] }
  }
  const session = createCameraSession({
    video,
    getUserMedia: media ?? (async () => newStream()),
    createTracker: () => {
      const tracker = { stops: 0, starts: 0, async start() { this.starts++; await start?.() }, stop() { this.stops++ }, latest: () => ({ tracked: 1 }) }
      trackers.push(tracker)
      return tracker
    },
    onState: (state) => states.push(state),
  })
  return { session, video, tracks, trackers, states, newStream }
}

test('successful camera, manual stop and restart release the previous stream', async () => {
  const f = fixture()
  f.session.setActive(true)
  await flush()
  assert.equal(f.states.at(-1), 'tracking')
  assert.equal(f.session.latest().tracked, 1)
  f.session.setActive(false)
  assert.equal(f.tracks[0].stops, 1)
  assert.equal(f.video.srcObject, null)
  assert.equal(f.session.latest(), null)
  f.session.setActive(true)
  await flush()
  assert.equal(f.states.at(-1), 'tracking')
  assert.equal(f.trackers.length, 2)
  f.session.setActive(false)
})

for (const failure of ['play', 'start']) {
  test(`${failure} failure turns off the camera and allows retry`, async () => {
    let fail = true
    const f = fixture({ [failure]: async () => { if (fail) throw new Error('simulated failure') } })
    f.session.setActive(true)
    await flush()
    assert.equal(f.states.at(-1), 'error')
    assert.equal(f.tracks[0].stops, 1)
    assert.equal(f.video.srcObject, null)
    assert.equal(f.session.latest(), null)
    fail = false
    f.session.setActive(true)
    await flush()
    assert.equal(f.states.at(-1), 'tracking')
    f.session.setActive(false)
  })
}

test('permission rejection stays idle without a retry loop', async () => {
  let requests = 0
  const f = fixture({ media: async () => { requests++; throw new Error('denied') } })
  f.session.setActive(true)
  await flush()
  await flush()
  assert.equal(f.states.at(-1), 'error')
  assert.equal(requests, 1)
  assert.equal(f.video.srcObject, null)
})

test('late permission approval after hide closes the returned stream', async () => {
  const pending = deferred()
  const f = fixture({ media: () => pending.promise })
  f.session.setActive(true)
  f.session.setActive(false)
  pending.resolve(f.newStream())
  await flush()
  assert.equal(f.states.at(-1), 'off')
  assert.equal(f.tracks[0].stops, 1)
  assert.equal(f.trackers[0].starts, 0)
})

test('hide/show while tracking initializes drains the old attempt and restarts', async () => {
  const pending = deferred()
  let calls = 0
  const f = fixture({ start: () => ++calls === 1 ? pending.promise : Promise.resolve() })
  f.session.setActive(true)
  await flush()
  f.session.setActive(false)
  f.session.setActive(true)
  assert.equal(f.tracks[0].stops, 1)
  pending.resolve()
  await flush()
  assert.equal(f.states.at(-1), 'tracking')
  assert.equal(f.trackers.length, 2)
  assert.equal(f.tracks[0].stops, 1)
  assert.equal(f.tracks[1].stops, 0)
  f.session.setActive(false)
})

test('disconnect releases camera and tracker and exposes retry state', async () => {
  const f = fixture()
  f.session.setActive(true)
  await flush()
  f.tracks[0].ended()
  assert.equal(f.states.at(-1), 'error')
  assert.equal(f.video.srcObject, null)
  assert.equal(f.session.latest(), null)
})

test('detector cleanup failure cannot keep a camera stream alive', async (t) => {
  const f = fixture()
  f.session.setActive(true)
  await flush()
  t.mock.method(console, 'warn', () => {})
  f.trackers[0].stop = () => { throw new Error('detector already closed') }
  f.session.setActive(false)
  assert.equal(f.tracks[0].stops, 1)
  assert.equal(f.video.srcObject, null)
  assert.equal(f.states.at(-1), 'off')
})

