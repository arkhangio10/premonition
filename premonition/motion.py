"""Puerto de movimiento. Esta entrega no contiene ningún transporte hacia actuadores reales."""


class MotionDisabled(RuntimeError):
    pass


class DisabledMotion:
    """Puerto por defecto fuera de simulación: rechaza toda orden."""

    kind = "deshabilitado"

    def execute(self, command):
        raise MotionDisabled("el movimiento físico está deshabilitado en esta entrega")

    def cancel(self):
        return "sin movimiento que cancelar"
