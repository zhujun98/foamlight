import unittest
from unittest.mock import MagicMock, patch
import functools

import numpy as np

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QSignalSpy, QTest
from PyQt5.QtWidgets import QWidget

from foamgraph import ImageViewF, PlotWidgetF

from foamlight import mkQApp
from foamlight.core import (
    _BaseAnalysisCtrlWidgetS, _FoamLightApp, create_app,
    QThreadKbClient, QThreadFoamClient, QThreadWorker
)
from foamlight.logger import logger

app = mkQApp()

logger.setLevel('CRITICAL')


class testCore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class DummyCtrlWidget(_BaseAnalysisCtrlWidgetS):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)

                self.dummy_widget = QWidget()
                self._non_reconfigurable_widgets = [
                    self.dummy_widget
                ]

        class DummyProcessor(QThreadWorker):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)

                self._dark_removed = False

            def process(self, data):
                """Override."""
                pass

            def onRemoveDark(self):
                """Override."""
                self._dark_removed = True

            def sources(self):
                return [
                    ("device1:output", "property1", 1),
                    ("device2", "property2", 0)
                ]

        class DummyImageView(ImageViewF):
            def __init__(self, *, parent=None):
                super().__init__(parent=parent)

            def updateF(self, data):
                """Override."""
                pass

        class DummyImageViewWithRoi(ImageViewF):
            def __init__(self, *, parent=None):
                super().__init__(has_roi=True, parent=parent)

            def updateF(self, data):
                """Override."""
                pass

        class DummyPlotWidget(PlotWidgetF):
            def __init__(self, *, parent=None):
                super().__init__(parent=parent)
                self._plot = self.plotCurve(name="dummy")

            def updateF(self, data):
                """Override."""
                pass

        @create_app(DummyCtrlWidget, DummyProcessor, QThreadKbClient)
        class DummyWindow(_FoamLightApp):
            _title = "Dummy"
            _long_title = "Dummy analysis"

            def __init__(self, topic):
                super().__init__(topic)

                self._line = DummyPlotWidget(parent=self)
                self._view = DummyImageView(parent=self)
                self._view_with_roi = DummyImageViewWithRoi(parent=self)

                self.initUI()
                self.initConnections()
                self.startWorker()

            def initUI(self):
                """Override."""
                pass

            def initConnections(self):
                """Override."""
                pass

        # Note: startWorker is not patched as it is in other tests of
        #       concrete windows
        cls._win = DummyWindow('DET')

    def testGeneral(self):
        self.assertEqual('DET', self._win._ctrl_widget_st.topic)

    def testPlotWidgets(self):
        win = self._win

        self.assertEqual(3, len(win._plot_widgets_st))
        self.assertIn(win._line, win._plot_widgets_st)
        self.assertIn(win._view, win._plot_widgets_st)
        self.assertEqual(2, len(win._image_views_st))
        self.assertIn(win._view, win._image_views_st)
        self.assertIn(win._view_with_roi, win._image_views_st)

        with patch.object(win._view, "updateImage") as update_image:
            QTest.mouseClick(win._com_ctrl_st.auto_level_btn, Qt.LeftButton)
            update_image.assert_called_once()

        with patch.object(win._view, "updateF") as update_view:
            with patch.object(win._line, "updateF") as update_line:
                win.updateWidgetsST()
                # win._data is empty
                update_line.assert_not_called()
                update_view.assert_not_called()
                # patch win._worker_st.get()
                with patch.object(win._worker_st, "getOutputDataST"):
                    win.updateWidgetsST()
                    update_line.assert_called_once()
                    update_view.assert_called_once()

    def testCommonStartStopReset(self):
        win = self._win
        com_ctrl_widget = win._com_ctrl_st
        ctrl_widget = win._ctrl_widget_st
        client = win._client_st
        worker = win._worker_st

        self.assertFalse(com_ctrl_widget.stop_btn.isEnabled())

        self.assertIsNone(client._endpoint_st)
        with patch.object(client, "start") as client_start:
            with patch.object(win._plot_timer_st, "start") as timer_start:
                spy = QSignalSpy(win.started_sgn)
                QTest.mouseClick(com_ctrl_widget.start_btn, Qt.LeftButton)

                self.assertEqual(f"tcp://{com_ctrl_widget._hostname_le.text()}:"
                                 f"{com_ctrl_widget._port_le.text()}", client._endpoint_st)

                self.assertEqual(2, len(client._catalog_st))
                self.assertIn("device1:output property1", client._catalog_st)
                self.assertIn("device2 property2", client._catalog_st)

                self.assertEqual(1, len(spy))
                self.assertTrue(com_ctrl_widget.stop_btn.isEnabled())
                self.assertFalse(com_ctrl_widget.start_btn.isEnabled())
                self.assertFalse(com_ctrl_widget.load_dark_run_btn.isEnabled())

                self.assertFalse(ctrl_widget.dummy_widget.isEnabled())

                client_start.assert_called_once()
                timer_start.assert_called_once()

        with patch.object(client, "terminateRunST") as client_stop:
            with patch.object(win._plot_timer_st, "stop") as timer_stop:
                spy = QSignalSpy(win.stopped_sgn)
                QTest.mouseClick(com_ctrl_widget.stop_btn, Qt.LeftButton)
                self.assertEqual(1, len(spy))
                self.assertFalse(com_ctrl_widget.stop_btn.isEnabled())
                self.assertTrue(com_ctrl_widget.start_btn.isEnabled())
                self.assertTrue(com_ctrl_widget.load_dark_run_btn.isEnabled())

                self.assertTrue(ctrl_widget.dummy_widget.isEnabled())

                client_stop.assert_called_once()
                timer_stop.assert_called_once()

        with patch.object(client, "start") as client_start:
            with patch.object(win._plot_timer_st, "start") as timer_start:
                with patch.object(worker, "sources") as mocked_sources:
                    with self.assertLogs(logger, level="ERROR") as cm:
                        mocked_sources.return_value = [("", "property1", 1)]
                        QTest.mouseClick(com_ctrl_widget.start_btn, Qt.LeftButton)
                        client_start.assert_not_called()
                        timer_start.assert_not_called()
                        self.assertIn("Empty source", cm.output[0])

                    with self.assertLogs(logger, level="ERROR") as cm:
                        mocked_sources.return_value = [("device", "", 0)]
                        QTest.mouseClick(com_ctrl_widget.start_btn, Qt.LeftButton)
                        client_start.assert_not_called()
                        timer_start.assert_not_called()
                        self.assertIn("Empty property", cm.output[0])

                    with self.assertLogs(logger, level="ERROR") as cm:
                        mocked_sources.return_value = [("device", "property", 2)]
                        QTest.mouseClick(com_ctrl_widget.start_btn, Qt.LeftButton)
                        client_start.assert_not_called()
                        timer_start.assert_not_called()
                        self.assertIn("Not understandable data type", cm.output[0])

        with patch.object(client, "onResetST") as client_reset:
            with patch.object(worker, "onResetST") as worker_reset:
                with patch.object(win._line, "reset") as line_reset:
                    with patch.object(win._view, "reset") as view_reset:
                        QTest.mouseClick(com_ctrl_widget.reset_btn, Qt.LeftButton)

                        client_reset.assert_called_once()
                        worker_reset.assert_called_once()
                        line_reset.assert_called_once()
                        view_reset.assert_called_once()

        with patch.object(worker._input_st, "clear") as input_clear:
            with patch.object(worker._output_st, "clear") as output_clear:
                worker._reset_st = False
                worker.onResetST()
                input_clear.assert_called_once()
                output_clear.assert_called_once()
                worker._reset_st = True

        with patch.object(client._transformer_st, "reset") as transformer_reset:
            with patch.object(client._output_st, "clear") as output_clear:
                client.onResetST()
                transformer_reset.assert_called_once()
                output_clear.assert_called_once()

    def testProcessFlow(self):
        worker = self._win._worker_st
        data = object()
        with patch.object(worker, "preprocess") as mocked_preprocess:
            with patch.object(worker, "process") as mocked_process:
                with patch.object(worker, "postprocess") as mocked_postprocess:
                    with patch.object(worker, "reset") as mocked_reset:
                        worker._reset_st = False
                        worker._processImpST(data)
                        mocked_preprocess.assert_called_once()
                        mocked_process.assert_called_once_with(data)
                        mocked_postprocess.assert_called_once()
                        mocked_reset.assert_not_called()

                        worker._reset_st = True
                        worker._processImpST(data)
                        mocked_reset.assert_called_once()
                        self.assertFalse(worker._reset_st)

    def testCommonDarkOperation(self):
        win = self._win
        widget = win._com_ctrl_st
        worker = win._worker_st

        # recording dark
        self.assertFalse(worker.recordingDark())  # default value
        QTest.mouseClick(widget.record_dark_btn, Qt.LeftButton)
        self.assertTrue(worker.recordingDark())
        self.assertTrue(widget.record_dark_btn.isChecked())
        QTest.mouseClick(widget.record_dark_btn, Qt.LeftButton)
        self.assertFalse(worker.recordingDark())
        self.assertFalse(widget.record_dark_btn.isChecked())

        # load dark run
        with patch.object(worker, "onLoadDarkRun") as load_dark_run:
            with patch('foamlight.core.QFileDialog.getExistingDirectory',
                       return_value=""):
                QTest.mouseClick(widget.load_dark_run_btn, Qt.LeftButton)
                load_dark_run.assert_not_called()

            with patch('foamlight.core.QFileDialog.getExistingDirectory',
                       return_value="/run/directory"):
                QTest.mouseClick(widget.load_dark_run_btn, Qt.LeftButton)
                load_dark_run.assert_called_with("/run/directory")

        # remove dark
        # patch.object does not work
        self.assertFalse(worker._dark_removed)
        QTest.mouseClick(widget.remove_dark_btn, Qt.LeftButton)
        self.assertTrue(worker._dark_removed)

        # subtract dark
        self.assertTrue(worker.subtractDark())  # default value
        widget.dark_subtraction_cb.setChecked(False)
        self.assertFalse(worker.subtractDark())

    def testRoiCtrl(self):
        pass

    def testSqueezeCameraImage(self):
        a1d = np.ones((4, ))
        a2d = np.ones((2, 1))
        a3d = np.ones((3, 3, 1))

        func = functools.partial(self._win._worker_st.squeezeToVector, 1234)

        assert func(None) is None
        assert func(a3d) is None

        ret_1d = func(a1d)
        np.testing.assert_array_equal(a1d, ret_1d)

        ret_2d = func(a2d)
        np.testing.assert_array_equal(a2d.squeeze(axis=-1), ret_2d)

    def testSqueezeToVector(self):
        a1d = np.ones((4, ))
        a2d = np.ones((2, 2))
        a3d = np.ones((3, 3, 1))
        a3d_f = np.ones((3, 3, 2))
        a4d = np.ones((2, 2, 2, 2))

        func = functools.partial(self._win._worker_st.squeezeToImage, 1234)

        assert func(None) is None
        assert func(a1d) is None
        assert func(a4d) is None

        ret_2d = func(a2d)
        np.testing.assert_array_equal(a2d, ret_2d)
        assert np.float32 == ret_2d.dtype

        ret_3d = func(a3d)
        np.testing.assert_array_equal(a3d.squeeze(axis=-1), ret_3d)
        assert np.float32 == ret_3d.dtype
        assert func(a3d_f) is None

    def testGetRoiData(self):
        worker = self._win._worker_st

        # test 2D array
        img = np.ones((4, 6))

        # test ROI geometry not specified
        worker._roi_geom_st = None
        roi = worker.getRoiData(img)
        assert img is roi
        roi = worker.getRoiData(img, copy=True)
        assert img is not roi
        np.testing.assert_array_equal(img, roi)

        # test with intersection
        worker._roi_geom_st = (1, 2, 2, 3)
        roi = worker.getRoiData(img)
        np.testing.assert_array_equal(img[2:5, 1:3], roi)

        # test without intersection
        worker._roi_geom_st = (-5, -6, 2, 3)
        roi = worker.getRoiData(img)
        np.testing.assert_array_equal(np.empty((0, 0)), roi)

        # test 3D array
        img = np.ones((3, 4, 6))

        # test with intersection
        worker._roi_geom_st = (1, 2, 2, 3)
        roi = worker.getRoiData(img)
        np.testing.assert_array_equal(img[:, 2:5, 1:3], roi)

        # test without intersection
        worker._roi_geom_st = (-5, -6, 2, 3)
        roi = worker.getRoiData(img)
        np.testing.assert_array_equal(np.empty((3, 0, 0)), roi)
