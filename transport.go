package modbus

type transportType uint
const (
	modbusRTU        transportType   = 1
	modbusRTUOverTCP transportType   = 2
	modbusRTUOverUDP transportType   = 3
	modbusASCII      transportType   = 4
	modbusTCP        transportType   = 5
	modbusTCPOverTLS transportType   = 6
	modbusTCPOverUDP transportType   = 7
)

type transport interface {
	Close()              (error)
	ExecuteRequest(*pdu) (*pdu, error)
	ReadRequest()        (*pdu, error)
	WriteResponse(*pdu)  (error)
}
