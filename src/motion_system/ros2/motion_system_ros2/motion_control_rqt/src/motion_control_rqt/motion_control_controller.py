from rqt_gui_py.plugin import Plugin

from motion_control_rqt.motor_manager_widget import MotorManagerWidget

class MotionControlController(Plugin):
    def __init__(self, context):
        super().__init__(context)

        self.setObjectName('MotionControlController')
        
        self.widget = MotorManagerWidget(context.node)

        serial_number = context.serial_number()
        if serial_number >= 1:
            self.widget.setWindowTitle(self.widget.windowTitle() + f' {serial_number}')
        
        context.add_widget(self.widget)

    def shutdown_plugin(self):
        print('MotionControlController shutdown')
        self.widget.shutdown_widget()
