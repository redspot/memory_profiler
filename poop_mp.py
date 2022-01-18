from contextlib import suppress
import multiprocessing
import multiprocessing.dummy
from multiprocessing.managers import BaseManager, SyncManager
from random import random
import sys
import time
from unittest.mock import Mock, patch

import psutil
import pytest

# make sure that memory profiler does not hang on exception
import memory_profiler


class MockMemoryInfo(Mock):
    """create a Mock version of psutil.Process.memory_full_info

    when this mock memory_full_info() is called:
        call the real memory_full_info()
        check if this is the Nth call, where N is in fail_when.
            if so, modify the attr_name attribute of the info
            to be None.
            then, return the info, changed or unchanged.
    example:
        >>> import os
        >>> import psutil
        >>> mfi = psutil.Process.memory_full_info
        >>> mock_mi = MockMemoryInfo(mfi)
        >>> p = psutil.Process(os.getpid())
        >>> p.memory_full_info().uss
        123456789
        >>> # patch original memory_full_info
        >>> psutil.Process.memory_full_info = mock_mi.bind()
        >>> # first call sets 'uss' to None
        >>> p.memory_full_info().uss is None
        True
        >>> # other calls use the real value from original
        >>> p.memory_full_info().uss
        123456789
        >>> mock_mi.mock_returns[0].uss is None
        True
        >>> mock_mi.mock_returns[1].uss
        123456789
        >>> mock_mi.reset_mock()
        >>> mock_mi.mock_returns = []
        >>> mock_mi.fail_when = [2]
        >>> # other calls use the real value from original
        >>> p.memory_full_info().uss
        123456789
        >>> # second call sets 'uss' to None
        >>> p.memory_full_info().uss is None
        True
        >>> mock_mi.mock_returns[0].uss
        123456789
        >>> mock_mi.mock_returns[1].uss is None
        True
        >>> # restore original memory_full_info
        >>> psutil.Process.memory_full_info = mfi
    """
    def __init__(self, orig_mem_info=psutil.Process.memory_full_info,
                 fail_when=[1], name='uss', *args, **kw):
        super().__init__(*args, **kw)
        self.fail_when = fail_when
        self.attr_name = name
        self.side_effect = self._wrap_mem_info(orig_mem_info)
        self.reset()
        self.shared_data = None
        self.parent_mock = None

    def reset(self):
        self.reset_mock()
        self.mock_returns = []

    def _wrap_mem_info(mock_self, orig_mem_info):
        """decorate orig_mem_info with mock version"""
        def mock_mem_info(*a, **kw):
            """if Nth call, replace attr_name value with None"""
            try:
                minfo = orig_mem_info(*a, **kw)
            except TypeError:
                if mock_self.parent_mock is not None:
                    minfo = orig_mem_info(mock_self.parent_mock(), *a, **kw)
                else:
                    raise
            print(f"s_mi={minfo}")
            print(f"cc={mock_self.call_count} fw={mock_self.fail_when}")
            if mock_self.call_count in mock_self.fail_when:
                minfo = minfo._replace(**{mock_self.attr_name: None})
            else:
                minfo = minfo._replace(**{mock_self.attr_name: 123456789})
            print(f"e_mi={minfo}")
            mock_self.mock_returns.append(minfo)
            if mock_self.shared_data is not None:
                mock_self.shared_data['call_count'] = mock_self.call_count
                mock_self.shared_data['mock_returns'].append(minfo)
                print("shared_data set:"
                      f" cc={mock_self.shared_data['call_count']}"
                      f" mr={mock_self.shared_data['mock_returns']}")
            return minfo
        return mock_mem_info

    def bind(self):
        """create a bound method that returns self.__call__()"""
        def bound_mem_info(*a, **kw):
            return self(*a, **kw)
        return bound_mem_info


def target_function(size=3000):
    stuff = [random() for _ in range(size)]
    time.sleep(1)
    stuff = [random() for _ in range(size)]
    return stuff


# @pytest.fixture(scope="session")
# def shared_mock():
#     orig_mem_info = psutil.Process.memory_full_info
#     mock_minfo = MockMemoryInfo(orig_mem_info)
#     yield mock_minfo
#
#
# @pytest.fixture(scope="session")  # , autouse=True)
# def mock_mgr(shared_mock):
#     # multiprocessing.set_start_method('fork', force=True)
#     global _get_mock
#
#     def _get_mock():
#         return shared_mock
#
#     BaseManager.register('get_mock', _get_mock)
#     mgr = BaseManager()
#     # mgr.get_server().serve_forever()
#     mgr.start()
#     yield mgr
#
#
# @pytest.fixture
# def mp_fork(monkeypatch):
#     ctx = multiprocessing.get_context('fork')
#     monkeypatch.setattr(memory_profiler, "Process", ctx.Process)
#     monkeypatch.setattr(memory_profiler, "Pipe", ctx.Pipe)
#     # monkeypatch.setattr(memory_profiler, "mp_conn", ctx.connection)
#     yield ctx
#
#
# @pytest.fixture
# def mock_mem_info(mock_mgr, mp_fork, monkeypatch):
#     mock_minfo = mock_mgr.get_mock()
#     mock_minfo.reset()
#     monkeypatch.setattr(psutil.Process, 'memory_full_info', mock_minfo.bind())
#     yield mock_minfo


class MockManager(BaseManager):
    pass


def show_decendents(tag=""):
    me = psutil.Process()
    print(f"{tag}me={me.pid}")
    children = [c.pid for c in me.children(recursive=True)]
    print(f"{tag}kids={children}")


def test_memory_usage_exception_in_get_memory_call(mock_mem_info, when):
    mock_mem_info.fail_when = when
    expected_count = max(when + [1])
    with pytest.raises(RuntimeError):
        memory_profiler.memory_usage(proc=target_function, max_usage=True, backend="psutil_uss")
    show_decendents("after_raises:")
    # assert mock_mem_info.call_count >= expected_count
    # assert mock_mem_info.mock_returns
    # assert all(mock_mem_info.mock_returns[i-1].uss is None
    #            for i in when)
    print("cc", mock_mem_info.call_count, expected_count)
    print("mr", mock_mem_info.mock_returns)
    # breakpoint()
    # print("s_cc", mock_mem_info.shared_data.get('call_count'))
    # print("s_mr", mock_mem_info.shared_data.get('mock_returns'))
    # print(all(mock_mem_info.mock_returns[i-1].uss is None for i in when))


def wrap_get_memory(mock_minfo):
    memory_metric = "uss"

    def mock_get_memory(*a, **kw):
        orig_Process = psutil.Process
        print("mock_get_memory top")
        pid = a[0]
        real_proc = orig_Process(pid)
        # mock_minfo.parent_mock = lambda: real_proc
        ret = mock_minfo.bind()(real_proc)
        print(f"ret={ret}")
        mem = getattr(ret, memory_metric)
        print(f"mem={mem}")
        print("mock_get_memory bottom")
        return mem
    return mock_get_memory


def main():
    show_decendents("top:")
    orig_mem_info = psutil.Process.memory_full_info
    shared_mock = MockMemoryInfo(orig_mem_info)
    # BaseManager.register('get_mock', callable=lambda: shared_mock)
    # MockManager.register('get_mock', callable=lambda: shared_mock)
    # mgr = BaseManager()
    mgr = SyncManager()
    # mgr = MockManager()
    mgr.start()
    show_decendents("mgr:")
    ctx = multiprocessing.get_context('fork')
    # mgr = ctx.Manager()
    print("mgr", mgr.address)
    shared_data = mgr.dict([("mock_returns", mgr.list())])
    print("shared_data", list(shared_data.keys()))
    shared_mock.shared_data = shared_data
    patch_Process = ctx.Process
    # patch_Process = multiprocessing.dummy.Process
    patch_Pipe = ctx.Pipe
    # patch_Pipe = multiprocessing.dummy.Pipe
    with patch.object(memory_profiler, "Process", patch_Process), \
            suppress(TypeError), \
            patch.object(memory_profiler.MemTimer, "__bases__", (patch_Process,)), \
            patch.object(memory_profiler, "Pipe", patch_Pipe):
        # mock_minfo = mgr.get_mock()
        mock_minfo = shared_mock
        mock_minfo.reset()
        mock_minfo.fail_when = [2]
        target = memory_profiler
        wrapped_target = wrap_get_memory(mock_minfo)
        with patch.object(target, '_get_memory', wrapped_target):
            test_memory_usage_exception_in_get_memory_call(mock_minfo, [2])
        show_decendents("after_test:")
        with suppress(Exception):
            print("shared_data", list(shared_data.keys()))
    with suppress(Exception):
        print("shared_data", list(shared_data.keys()))
    print("mgr", mgr.address)


if __name__ == '__main__':
    main_module = sys.modules['__main__']
    if not hasattr(main_module, '__spec__'):
        setattr(main_module, '__spec__', None)
    main()
