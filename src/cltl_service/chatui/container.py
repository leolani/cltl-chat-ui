import logging

from cltl.chatui.api import Chats, ImageStore
from cltl.chatui.memory import MemoryChats, MemoryImageStore
from cltl.combot.infra.container import InfraContainer
from cltl.combot.infra.di_container import singleton
from cltl_service.chatui.service import ChatUiService

logger = logging.getLogger(__name__)

DEFAULT_IMAGE_CACHE = 4
DEFAULT_IMAGE_MAX_SIZE = 10 * 1024 * 1024


class ChatUIContainer(InfraContainer):
    @property
    @singleton
    def chats(self) -> Chats:
        return MemoryChats()

    @property
    @singleton
    def image_store(self) -> ImageStore:
        """The upload cache, or False when image upload is switched off.

        `@singleton` cannot hold None — it uses the stored value's presence to
        decide whether the factory has run — so an intentionally absent optional
        service is False. Callers test truthiness.

        Named `image_store` rather than `image_storage`: `DIContainer._singletons`
        is keyed by method name across the whole process, and `image_storage` is
        already cltl-backend's.
        """
        config = self.config_manager.get_config("cltl.chat-ui")
        if "image_upload" not in config or not config.get_boolean("image_upload"):
            logger.info("Image upload is disabled for the Chat UI")
            return False

        capacity = config.get_int("image_cache") if "image_cache" in config else DEFAULT_IMAGE_CACHE
        max_size = (config.get_int("image_max_size") if "image_max_size" in config
                    else DEFAULT_IMAGE_MAX_SIZE)

        return MemoryImageStore(capacity, max_size)

    @property
    @singleton
    def chatui_service(self) -> ChatUiService:
        return ChatUiService.from_config(self.chats, self.image_store, self.event_bus,
                                         self.resource_manager, self.config_manager)

    def start(self):
        logger.info("Start Chat UI")
        super().start()
        self.chatui_service.start()

    def stop(self):
        logger.info("Stop Chat UI")
        self.chatui_service.stop()
        super().stop()
