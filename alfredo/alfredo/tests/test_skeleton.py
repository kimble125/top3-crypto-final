"""경계 시험: 모의 전용 패키지에 주문 계열 공개 이름이 없어야 한다(검수 1-2)."""
import importlib, pkgutil, unittest
import alfredo

FORBIDDEN = ("order", "place_", "execute", "submit")


class SkeletonTest(unittest.TestCase):
    def test_simulation_only_flag(self):
        self.assertTrue(getattr(alfredo, "SIMULATION_ONLY", False))

    def test_no_order_like_public_names(self):
        for m in pkgutil.iter_modules(alfredo.__path__):
            if m.name == "tests":
                continue
            mod = importlib.import_module(f"alfredo.{m.name}")
            for name in dir(mod):
                if name.startswith("_"):
                    continue
                low = name.lower()
                self.assertFalse(any(f in low for f in FORBIDDEN),
                                 f"주문 계열 이름 발견: alfredo.{m.name}.{name}")


if __name__ == "__main__":
    unittest.main()
