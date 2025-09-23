#!/usr/bin/env python3
"""
Tests for the events module (ChatCache, ResponseListener, EventManager)
"""
import pytest
import time
from unittest.mock import Mock, MagicMock

from src.events import ChatCache, ResponseListener, EventManager


class TestChatCache:
    """Test ChatCache functionality"""
    
    def test_basic_operations(self):
        """Test basic cache operations"""
        cache = ChatCache(ttl_seconds=60, max_size=10)
        
        # Test set and get
        test_data = {"chat_id": "123", "candidate": "张三", "message": "你好"}
        cache.set("123", test_data)
        
        retrieved = cache.get("123")
        assert retrieved is not None
        assert retrieved["chat_id"] == "123"
        assert retrieved["candidate"] == "张三"
        assert "ts" in retrieved  # timestamp should be added
        
        # Test non-existent key
        assert cache.get("999") is None
        
        # Test size
        assert cache.size() == 1
    
    def test_ttl_expiration(self):
        """Test TTL expiration logic"""
        cache = ChatCache(ttl_seconds=2, max_size=10)  # 2 second TTL
        
        # Add data
        cache.set("123", {"chat_id": "123", "data": "test"})
        assert cache.get("123") is not None
        
        # Manually set an old timestamp to simulate expiration
        old_data = cache.cache["123"].copy()
        old_data["ts"] = int(time.time()) - 10  # 10 seconds ago (way past TTL)
        cache.cache["123"] = old_data
        
        # Trigger pruning by calling get - should remove expired entry
        result = cache.get("123")
        assert result is None  # Should be expired and pruned
        
        # Verify it's actually removed from cache
        assert "123" not in cache.cache
        assert cache.size() == 0
    
    def test_max_size_limit(self):
        """Test maximum size limiting"""
        cache = ChatCache(ttl_seconds=3600, max_size=3)  # 3 items max
        
        # Add more items than max size
        for i in range(5):
            cache.set(str(i), {"chat_id": str(i), "data": f"test{i}"})
        
        # Should only have 3 items (most recent)
        assert cache.size() == 3
        
        # Oldest items should be removed
        assert cache.get("0") is None
        assert cache.get("1") is None
        assert cache.get("2") is not None
        assert cache.get("3") is not None
        assert cache.get("4") is not None
    
    def test_clear(self):
        """Test cache clearing"""
        cache = ChatCache()
        cache.set("123", {"chat_id": "123"})
        cache.set("456", {"chat_id": "456"})
        
        assert cache.size() == 2
        cache.clear()
        assert cache.size() == 0
        assert cache.get("123") is None


class TestResponseListener:
    """Test ResponseListener functionality"""
    
    def test_extract_chat_data(self):
        """Test chat data extraction"""
        cache = ChatCache()
        listener = ResponseListener(cache)
        
        # Test valid item
        test_item = {
            "chatId": "123",
            "userInfo": {"name": "张三"},
            "latestMessage": {"content": "你好"},
            "jobInfo": {"jobName": "Python工程师"},
            "status": "active"
        }
        
        result = listener._extract_chat_data(test_item)
        assert result is not None
        assert result["chat_id"] == "123"
        assert result["candidate"] == "张三"
        assert result["message"] == "你好"
        assert result["job_title"] == "Python工程师"
        assert result["status"] == "active"
        
        # Test missing chatId
        invalid_item = {"userInfo": {"name": "test"}}
        result = listener._extract_chat_data(invalid_item)
        assert result is None
    
    def test_register_listener(self):
        """Test listener registration"""
        cache = ChatCache()
        listener = ResponseListener(cache)
        
        # Mock context
        mock_context = Mock()
        listener.register(mock_context)
        
        # Should have called context.on with response handler
        mock_context.on.assert_called_once()
        call_args = mock_context.on.call_args
        assert call_args[0][0] == "response"
        assert callable(call_args[0][1])  # Handler function


class TestEventManager:
    """Test EventManager functionality"""
    
    def test_initialization(self):
        """Test event manager initialization"""
        manager = EventManager(ttl_seconds=1800, max_cache_size=2000)
        
        assert manager.chat_cache is not None
        assert manager.response_listener is not None
        assert manager.chat_cache.ttl_seconds == 1800
        assert manager.chat_cache.max_size == 2000
    
    def test_setup(self):
        """Test event manager setup"""
        manager = EventManager()
        mock_context = Mock()
        
        # Should not raise any exceptions
        manager.setup(mock_context)
        
        # Response listener should be registered
        assert manager.response_listener._registered == True
    
    def test_get_cached_messages(self):
        """Test getting cached messages"""
        manager = EventManager()
        
        # Add some test data to cache
        test_data1 = {
            "chat_id": "123",
            "candidate": "张三",
            "message": "你好",
            "status": "active",
            "job_title": "Python工程师"
        }
        test_data2 = {
            "chat_id": "456", 
            "candidate": "李四",
            "message": "谢谢",
            "status": "replied",
            "job_title": "Java工程师"
        }
        
        manager.chat_cache.set("123", test_data1)
        manager.chat_cache.set("456", test_data2)
        
        # Get cached messages
        messages = manager.get_cached_messages(limit=10)
        
        assert len(messages) == 2
        assert all("timestamp" in msg for msg in messages)
        assert any(msg["chat_id"] == "123" for msg in messages)
        assert any(msg["chat_id"] == "456" for msg in messages)
    
    def test_get_cache_stats(self):
        """Test cache statistics"""
        manager = EventManager(ttl_seconds=1800, max_cache_size=2000)
        
        stats = manager.get_cache_stats()
        assert "size" in stats
        assert "max_size" in stats
        assert "ttl_seconds" in stats
        assert stats["max_size"] == 2000
        assert stats["ttl_seconds"] == 1800
    
    def test_clear_cache(self):
        """Test cache clearing"""
        manager = EventManager()
        
        # Add test data
        manager.chat_cache.set("123", {"chat_id": "123"})
        assert manager.chat_cache.size() == 1
        
        # Clear cache
        manager.clear_cache()
        assert manager.chat_cache.size() == 0


def test_integration_workflow():
    """Test integration between components"""
    manager = EventManager(ttl_seconds=60, max_cache_size=100)
    
    # Simulate a chat response being processed
    test_item = {
        "chatId": "integration-test",
        "userInfo": {"name": "集成测试"},
        "latestMessage": {"content": "集成测试消息"},
        "jobInfo": {"jobName": "测试工程师"},
        "status": "new"
    }
    
    # Extract and cache data (simulating what response listener would do)
    extracted = manager.response_listener._extract_chat_data(test_item)
    if extracted:
        manager.chat_cache.set(extracted["chat_id"], extracted)
    
    # Verify data is cached and retrievable
    cached_messages = manager.get_cached_messages(limit=1)
    assert len(cached_messages) == 1
    assert cached_messages[0]["chat_id"] == "integration-test"
    assert cached_messages[0]["candidate"] == "集成测试"
    
    # Verify stats
    stats = manager.get_cache_stats()
    assert stats["size"] == 1
