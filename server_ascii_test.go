package modbus

import (
	"net"
	"testing"
	"time"
)

func TestASCIIServerReadWriteAndException(t *testing.T) {
	serverLink, clientLink := net.Pipe()
	defer clientLink.Close()

	th := &tcpTestHandler{}
	server, err := NewServer(&ServerConfiguration{
		URL: "ascii://virtual-device",
		serialLinkFactory: func(conf *serialPortConfig) (rtuLink, error) {
			return serverLink, nil
		},
	}, th)
	if err != nil {
		t.Fatalf("failed to create server: %v", err)
	}
	if err = server.Start(); err != nil {
		t.Fatalf("failed to start server: %v", err)
	}
	defer server.Stop()

	at := newASCIITransport(clientLink, "virtual-device", 19200, 200*time.Millisecond, nil)

	_, err = at.ExecuteRequest(&pdu{
		unitId:       9,
		functionCode: fcWriteSingleRegister,
		payload:      []byte{0x00, 0x03, 0xab, 0xcd},
	})
	if err != nil {
		t.Fatalf("write single register failed: %v", err)
	}

	res, err := at.ExecuteRequest(&pdu{
		unitId:       9,
		functionCode: fcReadHoldingRegisters,
		payload:      []byte{0x00, 0x03, 0x00, 0x01},
	})
	if err != nil {
		t.Fatalf("read holding registers failed: %v", err)
	}
	if len(res.payload) != 3 || res.payload[0] != 0x02 || res.payload[1] != 0xab || res.payload[2] != 0xcd {
		t.Fatalf("unexpected read-holding response payload: %#v", res.payload)
	}

	res, err = at.ExecuteRequest(&pdu{
		unitId:       3,
		functionCode: fcReadCoils,
		payload:      []byte{0x00, 0x00, 0x00, 0x01},
	})
	if err != nil {
		t.Fatalf("unexpected exception read error: %v", err)
	}
	if res.functionCode != (0x80|fcReadCoils) || len(res.payload) != 1 || res.payload[0] != exIllegalFunction {
		t.Fatalf("unexpected exception response: %#v", res)
	}
}
