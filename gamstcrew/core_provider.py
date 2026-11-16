from __future__ import annotations


class CoreProviderRuntime:
    """Crew-owned lifecycle for a real GAMST subprocess provider.

    GAMST remains responsible for capability validation, provider framing and
    observation contracts. The selected Python environment runs the worker;
    Crew does not merge its dependencies into the caller's environment.
    """

    def __init__(self, python, profile, config, *, startup_timeout=120, inference_timeout=30):
        self.python = python
        self.profile = profile
        self.config = config
        self.startup_timeout = startup_timeout
        self.inference_timeout = inference_timeout
        self.provider = None

    async def start(self):
        if self.provider is not None:
            raise RuntimeError("provider runtime is already running")
        try:
            from gamst import ProcessProvider
        except ImportError as exc:
            raise RuntimeError("CoreProviderRuntime requires gamst-sdk in the caller") from exc
        provider = await ProcessProvider.open(
            self.python,
            self.profile,
            self.config,
            startup_timeout=self.startup_timeout,
            inference_timeout=self.inference_timeout,
        )
        if self.provider is not None:
            await provider.close()
            raise RuntimeError("provider runtime was started concurrently")
        self.provider = provider

    async def process(self, frame):
        if self.provider is None:
            raise RuntimeError("provider runtime is not running")
        return await self.provider.process(frame)

    async def stop(self):
        provider, self.provider = self.provider, None
        if provider is not None:
            await provider.close()

    async def close(self):
        await self.stop()

    def health(self):
        provider = self.provider
        process = None if provider is None else provider._process
        return {
            "running": provider is not None and not provider.closed and process is not None and process.returncode is None,
            "returncode": None if process is None else process.returncode,
            "profile": self.profile,
            "clock_id": None if provider is None else provider.clock_id,
            "clock_epoch": None if provider is None else provider.clock_epoch,
        }

    @property
    def clock_id(self):
        return None if self.provider is None else self.provider.clock_id

    @property
    def clock_epoch(self):
        return None if self.provider is None else self.provider.clock_epoch

    @property
    def spec(self):
        if self.provider is None:
            raise RuntimeError("provider runtime is not running")
        return self.provider.spec
