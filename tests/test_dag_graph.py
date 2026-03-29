#!/usr/bin/env python3
"""
dag.graph 모듈 단위 테스트 — TaskNode, TaskDAG
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dag"))


from graph import TaskNode, TaskDAG


def _make_node(task_id, name="task", worker_type="coder", depends_on=None):
    return TaskNode(task_id, name, worker_type, f"do {name}", depends_on)


class TestTaskNode(unittest.TestCase):

    def test_defaults(self):
        n = _make_node("t1")
        self.assertEqual(n.status, "pending")
        self.assertEqual(n.depends_on, [])
        self.assertEqual(n.cost_usd, 0.0)

    def test_to_dict_roundtrip(self):
        n = _make_node("t1", depends_on=["t0"])
        n.status = "completed"
        n.cost_usd = 1.5
        d = n.to_dict()
        restored = TaskNode.from_dict(d)
        self.assertEqual(restored.id, "t1")
        self.assertEqual(restored.status, "completed")
        self.assertEqual(restored.depends_on, ["t0"])
        self.assertAlmostEqual(restored.cost_usd, 1.5)


class TestTaskDAG(unittest.TestCase):

    def _linear_dag(self):
        """A → B → C"""
        dag = TaskDAG()
        dag.add_task(_make_node("A"))
        dag.add_task(_make_node("B", depends_on=["A"]))
        dag.add_task(_make_node("C", depends_on=["B"]))
        return dag

    def _diamond_dag(self):
        """A → B, A → C, B+C → D"""
        dag = TaskDAG()
        dag.add_task(_make_node("A"))
        dag.add_task(_make_node("B", depends_on=["A"]))
        dag.add_task(_make_node("C", depends_on=["A"]))
        dag.add_task(_make_node("D", depends_on=["B", "C"]))
        return dag

    # ── validate ──

    def test_valid_dag(self):
        ok, msg = self._linear_dag().validate()
        self.assertTrue(ok)
        self.assertEqual(msg, "OK")

    def test_missing_dependency(self):
        dag = TaskDAG()
        dag.add_task(_make_node("X", depends_on=["MISSING"]))
        ok, msg = dag.validate()
        self.assertFalse(ok)
        self.assertIn("unknown task", msg)

    def test_cycle_detection(self):
        dag = TaskDAG()
        dag.add_task(_make_node("A", depends_on=["B"]))
        dag.add_task(_make_node("B", depends_on=["A"]))
        ok, msg = dag.validate()
        self.assertFalse(ok)
        self.assertIn("Cycle", msg)

    # ── topological_sort ──

    def test_topo_sort_linear(self):
        order = self._linear_dag().topological_sort()
        self.assertEqual(order, ["A", "B", "C"])

    def test_topo_sort_diamond(self):
        order = self._diamond_dag().topological_sort()
        self.assertLess(order.index("A"), order.index("B"))
        self.assertLess(order.index("A"), order.index("C"))
        self.assertLess(order.index("B"), order.index("D"))
        self.assertLess(order.index("C"), order.index("D"))

    # ── get_ready_tasks ──

    def test_ready_tasks_initial(self):
        dag = self._diamond_dag()
        ready = dag.get_ready_tasks()
        self.assertEqual([t.id for t in ready], ["A"])

    def test_ready_tasks_after_completion(self):
        dag = self._diamond_dag()
        dag.nodes["A"].status = "completed"
        ready = sorted(t.id for t in dag.get_ready_tasks())
        self.assertEqual(ready, ["B", "C"])

    def test_ready_tasks_diamond_convergence(self):
        dag = self._diamond_dag()
        dag.nodes["A"].status = "completed"
        dag.nodes["B"].status = "completed"
        # C is still pending → D not ready
        ready = [t.id for t in dag.get_ready_tasks()]
        self.assertIn("C", ready)
        self.assertNotIn("D", ready)

    def test_ready_tasks_all_deps_met(self):
        dag = self._diamond_dag()
        for nid in ("A", "B", "C"):
            dag.nodes[nid].status = "completed"
        ready = [t.id for t in dag.get_ready_tasks()]
        self.assertEqual(ready, ["D"])

    # ── parallel_groups ──

    def test_parallel_groups_diamond(self):
        groups = self._diamond_dag().get_parallel_groups()
        self.assertEqual(groups[0], ["A"])
        self.assertEqual(sorted(groups[1]), ["B", "C"])
        self.assertEqual(groups[2], ["D"])

    def test_parallel_groups_independent(self):
        dag = TaskDAG()
        dag.add_task(_make_node("X"))
        dag.add_task(_make_node("Y"))
        dag.add_task(_make_node("Z"))
        groups = dag.get_parallel_groups()
        self.assertEqual(len(groups), 1)
        self.assertEqual(sorted(groups[0]), ["X", "Y", "Z"])

    # ── is_complete / has_failures ──

    def test_is_complete(self):
        dag = self._linear_dag()
        self.assertFalse(dag.is_complete())
        for n in dag.nodes.values():
            n.status = "completed"
        self.assertTrue(dag.is_complete())

    def test_has_failures(self):
        dag = self._linear_dag()
        self.assertFalse(dag.has_failures())
        dag.nodes["B"].status = "failed"
        self.assertTrue(dag.has_failures())

    # ── serialization ──

    def test_to_dict_from_dict(self):
        dag = self._diamond_dag()
        dag.nodes["A"].status = "completed"
        d = dag.to_dict()
        restored = TaskDAG.from_dict(d)
        self.assertEqual(len(restored.nodes), 4)
        self.assertEqual(restored.nodes["A"].status, "completed")

    def test_to_mermaid(self):
        mermaid = self._linear_dag().to_mermaid()
        self.assertIn("graph TD", mermaid)
        self.assertIn("A -->", mermaid)

    # ── empty dag ──

    def test_empty_dag(self):
        dag = TaskDAG()
        self.assertTrue(dag.is_complete())
        self.assertFalse(dag.has_failures())
        ok, msg = dag.validate()
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
