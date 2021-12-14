import qt, ctk, vtk
from SegmentEditorEffects import *
from slicer.ScriptedLoadableModule import *
import slicer
import os
import numpy as np
import logging
from collections import OrderedDict
from tempfile import TemporaryDirectory, NamedTemporaryFile

import HeartValveLib
from MONAILabel import MONAILabelLogic
from MONAILabelLib import MONAILabelClient

import time


PROGRESS_VALUES = {
  0: "%p%: Initializing",
  25: "%p%: Data Preparation",
  50: "%p%: Sending Data",
  75: "%p%: Running Inference",
  100: "%p%: Importing Results"
}

PARAM_DEFAULTS = {

}

class SegmentEditorEffect(AbstractScriptedSegmentEditorEffect):
  """This effect uses Watershed algorithm to partition the input volume"""

  @property
  def serverUrl(self):
      serverUrl = self.ui.serverComboBox.currentText
      return serverUrl

  def __init__(self, scriptedEffect):
    scriptedEffect.name = 'DeepHeart'
    scriptedEffect.perSegment = False # this effect operates on all segments at once (not on a single selected segment)
    scriptedEffect.requireSegments = False # this effect requires segment(s) existing in the segmentation
    AbstractScriptedSegmentEditorEffect.__init__(self, scriptedEffect)

    if (slicer.app.majorVersion >= 5) or (slicer.app.majorVersion >= 4 and slicer.app.minorVersion >= 11):
      scriptedEffect.requireSegments = False

    self.moduleName = "SegmentEditorDeepHeart"
    self.logic = DeepHeartLogic()

  def resourcePath(self, filename):
    scriptedModulesPath = os.path.dirname(slicer.util.modulePath(self.moduleName))
    return os.path.join(scriptedModulesPath, 'Resources', filename)

  def clone(self):
    # It should not be necessary to modify this method
    import qSlicerSegmentationsEditorEffectsPythonQt as effects
    clonedEffect = effects.qSlicerSegmentEditorScriptedEffect(None)
    clonedEffect.setPythonSource(__file__.replace('\\','/'))
    return clonedEffect

  def icon(self):
    # It should not be necessary to modify this method
    iconPath = os.path.join(os.path.dirname(__file__), 'SegmentEditorEffect.png')
    if os.path.exists(iconPath):
      return qt.QIcon(iconPath)
    return qt.QIcon()

  def helpText(self):
    return """TODO"""

  # user can select model
  # assessing if model is valid to be used with selected heartvalve node
  # make sure that heart valves available and disable UI if not
  def setupOptionsFrame(self):
    uiWidget = slicer.util.loadUI(self.resourcePath(f"{self.moduleName}.ui"))
    self.scriptedEffect.addOptionsWidget(uiWidget)
    self.ui = slicer.util.childWidgetVariables(uiWidget)

    settings = qt.QSettings()
    self.ui.serverComboBox.currentText = settings.value("DeepHeart/serverUrl", "http://127.0.0.1:8000")
    self.ui.progressBar.hide()
    self.ui.statusLabel.hide()

    self.ui.fetchServerInfoButton.connect("clicked(bool)", self.onClickFetchInfo)
    self.ui.serverComboBox.connect("currentIndexChanged(int)", self.onClickFetchInfo)
    self.ui.segmentationModelSelector.connect("currentIndexChanged(int)", self.onSegmentationModelSelected)
    # self.ui.segmentationModelSelector.connect("currentIndexChanged(int)", self.updateParameterNodeFromGUI)
    self.ui.segmentationButton.connect("clicked(bool)", self.onClickSegmentation)
    self.updateServerUrlGUIFromSettings()

  def initializeParameterNode(self):
    if self._parameterNode is not None:
      self._parameterNode = \
        self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)
    self.setParameterNode(self.logic.getParameterNode())

  def setParameterNode(self, inputParameterNode):
    self._parameterNode = inputParameterNode

    if self._parameterNode is not None:
      self.logic.setDefaultParameters(inputParameterNode)
      self.addObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)

    self.updateGUIFromParameterNode()

  def onClickFetchInfo(self):
    self.saveServerUrl()
    self.ui.appComboBox.clear()
    serverUrl = self.ui.serverComboBox.currentText
    info = self.logic.fetchInfo(serverUrl)
    self.ui.appComboBox.addItem(info.get("name", ""))

    from HeartValveLib.helpers import getValveModelForSegmentationNode
    segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
    valveModel = getValveModelForSegmentationNode(segmentationNode)

    # from ExportHeartDataLib import reference_volume
    # from ExportHeartDataLib.base import ExportItem, ExportSummary
    #
    # start = time.time()
    #
    #
    # ExportItem.referenceVolumeNode = \
    #   reference_volume.getNormalizedReferenceVolumeNode(valveModel,
    #                                                     exportSettings["volume_dimensions"],
    #                                                     exportSettings["voxel_spacing"])
    # ExportItem.probeToRasTransform = valveModel.getProbeToRasTransformNode()
    # ExportItem.setExportSummarizer(ExportSummary())
    #
    # from ExportHeartDataLib.items import PhaseFrame, Annulus
    # normalizedVolume = PhaseFrame(valveModel).getVolumeFrame()
    # ExportItem.saveNode(normalizedVolume, temp_dir / f"img.nii.gz", kind='mid-systolic-images')
    #
    # annulusNode = Annulus(valveModel).getAnnulusLabel()
    # ExportItem.saveNode(annulusNode, temp_dir / f"ann.nii.gz", kind='mid-systolic-annulus')
    #
    # exported_dict = ExportItem.exportSummarizer.get_summary()
    # print(exported_dict)

    # TODO: precheck if scene is valid and also if there are multiple
    # TODO: ExportHeartData should take valveModel of the segmentation as main segmentation phase to work on???

    self._updateModelSelector(self.ui.segmentationModelSelector, "DeepHeartSegmentation", valveModel.getValveType())

  def saveServerUrl(self):
    settings = qt.QSettings()
    serverUrl = self.ui.serverComboBox.currentText
    settings.setValue("DeepHeart/serverUrl", serverUrl)
    self._updateServerHistory(serverUrl)
    
    self.updateServerUrlGUIFromSettings()

  def updateParameterNodeFromGUI(self, caller=None, event=None):
    if self._parameterNode is None or self._updatingGUIFromParameterNode:
      return

    wasModified = self._parameterNode.StartModify()

    # TODO: update info here

    self._parameterNode.EndModify(wasModified)

  def _updateServerHistory(self, serverUrl):
    settings = qt.QSettings()
    serverUrlHistory = settings.value("DeepHeart/serverUrlHistory")
    if serverUrlHistory:
      serverUrlHistory = serverUrlHistory.split(";")
    else:
      serverUrlHistory = []
    try:
      serverUrlHistory.remove(serverUrl)
    except ValueError:
      pass
    serverUrlHistory.insert(0, serverUrl)
    serverUrlHistory = serverUrlHistory[:10]  # keep up to first 10 elements
    settings.setValue("DeepHeart/serverUrlHistory", ";".join(serverUrlHistory))

  def updateServerUrlGUIFromSettings(self):
    # Save current server URL to the top of history
    settings = qt.QSettings()
    serverUrlHistory = settings.value("DeepHeart/serverUrlHistory")

    wasBlocked = self.ui.serverComboBox.blockSignals(True)
    self.ui.serverComboBox.clear()
    if serverUrlHistory:
      self.ui.serverComboBox.addItems(serverUrlHistory.split(";"))
    self.ui.serverComboBox.setCurrentText(settings.value("DeepHeart/serverUrl"))
    self.ui.serverComboBox.blockSignals(wasBlocked)

  def createCursor(self, widget):
    # Turn off effect-specific cursor for this effect
    return slicer.util.mainWindow().cursor

  def updateGUIFromMRML(self):
    pass

  def updateMRMLFromGUI(self):
    pass

  def updateProgress(self, value):
    self.ui.progressBar.setValue(value)
    self.ui.progressBar.setStyleSheet(
     """
      QProgressBar {
        text-align: center;
      }
      QProgressBar::chunk {
        background-color: qlineargradient(x0: 0, x2: 1, stop: 0 orange, stop:1 green )
      }
      """
    )

    self.ui.progressBar.setFormat(PROGRESS_VALUES[value])
    slicer.app.processEvents()
    if value == 100:
      self.ui.progressBar.hide()
    else:
      self.ui.progressBar.show()

  def onSegmentationModelSelected(self):
    segmentationModelIndex = self.ui.segmentationModelSelector.currentIndex
    self.ui.segmentationButton.setEnabled(self.ui.segmentationModelSelector.itemText(segmentationModelIndex) != "")

  def onClickSegmentation(self):
    try:
      import nibabel as nib
    except ImportError:
      slicer.utils.pip_install("nibabel")

    segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
    modelName = self.ui.segmentationModelSelector.currentText
    serverUrl = self.ui.serverComboBox.currentText
    # TODO: check scene if everything needed for the selected model is available
    # TODO: check if selected segmentation Node belongs to the main segmentation heart valve

    self.updateProgress(0)

    with TemporaryDirectory() as temp_dir:
      result_file = None
      try:
        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        result_file = self.logic.infer(serverUrl, modelName, temp_dir, progressCallback=self.updateProgress)
        if result_file:
          labelNode = slicer.util.loadLabelVolume(str(result_file))

          tlogic = slicer.modules.terminologies.logic()
          terminologyName = tlogic.LoadTerminologyFromFile(HeartValveLib.getTerminologyFile())
          terminologyEntry = slicer.vtkSlicerTerminologyEntry()
          terminologyEntry.SetTerminologyContextName(terminologyName)

          segmentation = segmentationNode.GetSegmentation()
          numberOfExistingSegments = segmentation.GetNumberOfSegments()
          slicer.vtkSlicerSegmentationsModuleLogic.ImportLabelmapToSegmentationNode(labelNode,
                                                                                    segmentationNode,
                                                                                    terminologyName)
          slicer.mrmlScene.RemoveNode(labelNode)

          numberOfAddedSegments = segmentation.GetNumberOfSegments() - numberOfExistingSegments
          addedSegmentIds = [
            segmentation.GetNthSegmentID(numberOfExistingSegments + i) for i in range(numberOfAddedSegments)
          ]
          model = self.logic.models[modelName]
          for segmentId, segmentName in zip(addedSegmentIds, model["labels"]):
            segment = segmentation.GetSegment(segmentId)
            segment.SetName(segmentName)
            segType = getSegmentTerminologyByName(terminologyName, segmentName)
            if not segType:
              logging.info(f"No terminology entry found for segment with name {segmentName}. Using default colors.")
            segment.SetColor(np.array(segType.GetRecommendedDisplayRGBValue()) / 255.0)

            # TODO: apply SlicerHeart terminology!
            tagName = slicer.vtkSegment.GetTerminologyEntryTagName()

      except Exception as exc:
        import traceback
        traceback.print_exc()
        slicer.util.errorDisplay(
          "Failed to run inference in MONAI Label Server", detailedText=traceback.format_exc()
        )
      finally:
        qt.QApplication.restoreOverrideCursor()
        if result_file and os.path.exists(result_file):
          os.unlink(result_file)

  def _updateModelSelector(self, selector, modelType, valveType):
      self.ui.statusLabel.plainText = ''
      wasSelectorBlocked = selector.blockSignals(True)
      selector.clear()
      num_eligible = 0
      for model_name, model in self.logic.models.items():
          if model["type"] == modelType and model["valve_type"] == valveType:
              selector.addItem(model_name)
              selector.setItemData(selector.count - 1, model["description"], qt.Qt.ToolTipRole)
              num_eligible += 1
      selector.blockSignals(wasSelectorBlocked)
      self.onSegmentationModelSelected()
      if not num_eligible:
        msg = f"No eligible models were found for current valve type: {valveType}.\t\n"
      else:
        msg = f"Found {num_eligible} eligible models were found for current valve type: {valveType}.\t\n"
      msg += "-----------------------------------------------------\t\n"
      msg += f"Total Models Available:  {len(self.logic.models)}\t\n"
      msg += "-----------------------------------------------------\t\n"

      self.ui.statusLabel.plainText = msg
      self.ui.statusLabel.show()
      qt.QTimer.singleShot(10000, lambda: self.ui.statusLabel.hide())


class DeepHeartLogic(ScriptedLoadableModuleLogic):

  @staticmethod
  def setDefaultParameters(parameterNode, defaults=PARAM_DEFAULTS):
    for paramName, paramDefaultValue in defaults.items():
      if not parameterNode.GetParameter(paramName):
        parameterNode.SetParameter(paramName, str(paramDefaultValue))

  def __init__(self):
    ScriptedLoadableModuleLogic.__init__(self)
    self.logic = MONAILabelLogic()
    self.models = OrderedDict()

  def fetchInfo(self, serverUrl):
    self.models = OrderedDict()
    try:
      start = time.time()
      self.logic.setServer(serverUrl)
      info = self.logic.info()
      logging.info("Time consumed by fetch info: {0:3.1f}".format(time.time() - start))
      self._updateModels(info["models"])
      return info
    except Exception as exc:
      print(exc)
      import traceback
      slicer.util.errorDisplay(
        "Failed to fetch models from remote server. "
        "Make sure server address is correct and <server_uri>/info/ "
        "is accessible in browser",
        detailedText=traceback.format_exc(),
      )

  def _updateModels(self, models):
    self.models.clear()
    model_count = {}
    for k, v in models.items():
      model_type = v.get("type", "segmentation")
      model_count[model_type] = model_count.get(model_type, 0) + 1

      logging.debug("{} = {}".format(k, model_type))
      self.models[k] = v

  def infer(self, serverUrl, modelName, temp_dir, progressCallback):
    progressCallback(25)
    image_in = self.preprocessSceneData(modelName, temp_dir)

    progressCallback(50)
    client = MONAILabelClient(server_url=serverUrl)
    sessionId = client.create_session(image_in)["session_id"]

    progressCallback(75)
    result_file, params = client.infer(model=modelName,
                                       image_in=image_in,
                                       params={},
                                       session_id=sessionId)

    progressCallback(100)

    return result_file

  def preprocessSceneData(self, modelName, temp_dir):
    start = time.time()
    exportSettings = self.models[modelName]["config"]["model_attributes"]
    exporter = InferenceExporter(input_data=slicer.mrmlScene,
                                 output_directory=temp_dir,
                                 **exportSettings)
    satisfied, messages = exporter.checkRequirements()
    if not satisfied:
      slicer.util.errorDisplay(
        "Model requirements not satisfied", detailedText=messages
      )
      raise ValueError("Model requirements not satisfied")
    exported_dict = exporter.export()

    volumes = [exported_dict[key][0] for key in self.models[modelName]["config"]["export_keys"]]
    image_in = _stackVolumes(volumes, temp_dir)
    logging.info("Time consumed to preprocess data: {0:3.1f}".format(time.time() - start))
    return image_in


class InferenceExporter(object):

  def __init__(self,
               valve_type,
               input_data=None,
               phases=None,
               output_directory=None,
               voxel_spacing=None,
               volume_dimensions=None,
               landmark_labels=None):

    from ExportHeartDataLib.export import Exporter
    self._exporter = Exporter(valve_type,
                              input_data=input_data,
                              phases=phases,
                              output_directory=output_directory,
                              volume_dimensions=volume_dimensions,
                              voxel_spacing=voxel_spacing,
                              landmark_labels=landmark_labels,
                              annulus_contour_label=True)

  def checkRequirements(self):
    return self._exporter.checkRequirements()

  def export(self):
    return self._exporter.export()


def _stackVolumes(volumes: list, out_dir: str):
  import nibabel as nib
  affine = nib.load(volumes[0]).affine
  dtype = np.float32
  data = np.stack([nib.load(path).get_fdata().astype(dtype) for path in volumes])
  img = nib.Nifti1Image(data, affine)
  in_file = NamedTemporaryFile(suffix=".nii.gz", dir=out_dir).name
  nib.save(img, in_file)
  return in_file


def getSegmentTerminologyByName(terminologyName, name):
  tlogic = slicer.modules.terminologies.logic()
  cat = slicer.vtkSlicerTerminologyCategory()
  tlogic.GetNthCategoryInTerminology(terminologyName, 0, cat)
  segType = slicer.vtkSlicerTerminologyType()
  for idx in range(tlogic.GetNumberOfTypesInTerminologyCategory(terminologyName, cat)):
    tlogic.GetNthTypeInTerminologyCategory(terminologyName, cat, idx, segType)
    if segType.GetCodeMeaning() == name:
      return segType
  raise None