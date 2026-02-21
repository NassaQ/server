from abc import ABC, abstractmethod
import json
from typing import Awaitable, Callable
import aio_pika

class BaseBroker(ABC):
    @abstractmethod
    async def connect(self):
        """Establish connection"""
        pass

    @abstractmethod
    async def publish(self, queue_name: str, message: dict):
        """Send a message"""
        pass

    @abstractmethod
    async def close(self):
        """Close connection"""
        pass

class RabbitMQBroker(BaseBroker):
    def __init__(self, amqp_url: str):
        self.url = amqp_url
        self.connection = None
        self.channel = None

    async def connect(self):
        self.connection = await aio_pika.connect_robust(self.url)
        self.channel = await self.connection.channel()

    async def publish(self, queue_name: str, message: dict):
        await self.channel.declare_queue(queue_name, durable=True)
        
        await self.channel.default_exchange.publish(
            aio_pika.Message(
                body=json.dumps(message).encode(),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT
            ),
            routing_key=queue_name,
        )
    
    async def consume(self, queue_name: str, callback: Callable[[dict], Awaitable[None]]):
        await self.channel.set_qos(prefetch_count=1)
        queue = await self.channel.declare_queue(queue_name, durable=True)

        async def on_message(message: aio_pika.abc.AbstractIncomingMessage):
            async with message.process(requeue=True):
                body = json.loads(message.body.decode())
                await callback(body)
        
        await queue.consume(on_message)

    async def close(self):
        if self.connection:
            await self.connection.close()


class AzureServiceBusBroker(BaseBroker):
    async def connect(self):
        pass 
    
    async def publish(self, queue_name: str, message: dict):
        pass 

    async def consume(self, queue_name: str, callback: Callable[[dict], Awaitable[None]]):
        pass 

    async def close(self):
        pass

