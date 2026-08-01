# Desc: Nova D1 background jobs — run slow work on the shared loop, not in tick().
# File: /Packages/NovaD1/novajob.py
#
# A leaf (L0): imports nothing from the package. MicroPython-safe: no f-strings.
#
# The problem this exists for: a screen that does slow work inside tick() blocks
# the ONE cooperative event loop the whole device shares — the GUI, the serial
# shell and every background service. While it is blocked nothing repaints (so the
# spinner that is meant to say "still working" sits frozen, saying the opposite)
# and no button can be acted on. Checking for updates froze the device for ten
# seconds or more that way.
#
# A Job moves that work into an asyncio task. The screen keeps returning from
# tick() immediately and reads the job's state instead. Because the loop keeps
# turning, three things follow at once: the spinner animates, the shell stays
# responsive, and HOME can be acted on WHILE the work is still running.
#
# What this does NOT do: make synchronous code interruptible. A coroutine that
# calls a blocking function still blocks the loop for its duration — the win comes
# from awaiting genuinely async work (net.awget yields on every socket wait). Work
# that has no async form should be split into steps that await between them.

RUNNING = 'running'
DONE = 'done'
ERROR = 'error'


class Job:
    """One unit of background work.

    The coroutine is passed the Job itself so it can report progress
    (`job.status = 'Checking OS...'`) and notice cancellation
    (`if job.cancelled(): return`). Everything the screen needs to render is a
    plain attribute read, so drawing never has to touch asyncio."""

    def __init__(self, status='Working...'):
        self.state = RUNNING
        self.result = None
        self.error = ''
        self.status = status
        self._task = None
        self._cancel = False

    def cancelled(self):
        return self._cancel

    def running(self):
        return self.state == RUNNING

    def cancel(self):
        """Ask the job to stop.

        Both halves matter. The flag is cooperative and is what a well-behaved
        coroutine checks between steps; task.cancel() handles the case where it is
        parked on an await and would otherwise never look. Cancelling is always
        safe to call twice, and safe on a job that has already finished."""
        self._cancel = True
        t = self._task
        if t is not None:
            try:
                t.cancel()
            except Exception:
                pass

    def failed(self):
        return self.state == ERROR


async def _runner(job, coro_fn, args):
    try:
        job.result = await coro_fn(job, *args)
    except BaseException as e:
        # BaseException, not Exception. CancelledError — what task.cancel() raises
        # into an awaiting coroutine — derives from BaseException in both CPython
        # and MicroPython, so `except Exception` misses precisely the case cancel()
        # creates and leaves the job reporting RUNNING for ever. A screen watching
        # that flag would spin on work that had already stopped.
        #
        # A cancelled job says 'Cancelled' rather than naming the exception: the
        # user asked for it, so it is not a fault to report.
        job.error = 'Cancelled' if job._cancel else (str(e) or e.__class__.__name__)
        job.state = ERROR
        return
    if job._cancel:
        job.state = ERROR
        job.error = job.error or 'Cancelled'
    else:
        job.state = DONE


def start(coro_fn, *args, **kw):
    """Run coro_fn(job, *args) on the shared event loop; return the Job at once.

    Never raises. With no running loop — the host tests, or a context where the
    GUI is not being driven by asyncio — the job comes back already in ERROR so
    the caller renders a message instead of waiting forever for a task that was
    never scheduled."""
    job = Job(kw.get('status', 'Working...'))
    coro = None
    try:
        import asyncio
        coro = _runner(job, coro_fn, args)
        job._task = asyncio.create_task(coro)
        coro = None                  # scheduled; the loop owns it now
    except Exception as e:
        job.state = ERROR
        job.error = str(e) or 'no event loop'
    if coro is not None:
        # create_task raised, so nothing will ever await this coroutine object.
        # Closing it releases its frame instead of leaving it for the collector —
        # which matters more here than the warning it silences, because on this
        # device an abandoned frame is heap that does not come back until a GC.
        try:
            coro.close()
        except Exception:
            pass
    return job


# A spinner the screens share, so "busy" looks the same everywhere. Four frames of
# a rotating bar: it reads as motion at this size, where a braille spinner is a
# smudge and a dot sequence is easy to mistake for a frozen ellipsis.
SPIN = ('-', '\\', '|', '/')


def spin(n):
    return SPIN[int(n) % len(SPIN)]
