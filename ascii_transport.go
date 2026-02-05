package modbus

import (
	"encoding/hex"
	"fmt"
	"log"
	"os"
	"time"
)

const (
	maxASCIIFrameLength int = 513
)

type asciiTransport struct {
	logger       *logger
	link         rtuLink
	timeout      time.Duration
	lastActivity time.Time
	t35          time.Duration
	t1           time.Duration
}

// Returns a new ASCII transport.
func newASCIITransport(link rtuLink, addr string, speed uint, timeout time.Duration, customLogger *log.Logger) (at *asciiTransport) {
	// default to 19200 if no speed is provided (e.g. when tunneling over TCP/UDP)
	if speed == 0 {
		speed = 19200
	}

	at = &asciiTransport{
		logger:  newLogger(fmt.Sprintf("ascii-transport(%s)", addr), customLogger),
		link:    link,
		timeout: timeout,
		t1:      serialCharTime(speed),
	}

	if speed >= 19200 {
		at.t35 = 1750 * time.Microsecond
	} else {
		at.t35 = (serialCharTime(speed) * 35) / 10
	}

	return
}

// Closes the ASCII link.
func (at *asciiTransport) Close() (err error) {
	err = at.link.Close()

	return
}

// Runs a request across the link and returns a response.
func (at *asciiTransport) ExecuteRequest(req *pdu) (res *pdu, err error) {
	var ts time.Time
	var t time.Duration
	var n int

	err = at.link.SetDeadline(time.Now().Add(at.timeout))
	if err != nil {
		return
	}

	// respect inter-frame delay
	t = time.Since(at.lastActivity.Add(at.t35))
	if t < 0 {
		time.Sleep(-t)
	}

	ts = time.Now()

	frame := at.assembleASCIIFrame(req)
	n, err = at.link.Write(frame)
	if err != nil {
		return
	}

	// estimate time on the wire; ASCII frames are text, so use char time * bytes written
	at.lastActivity = ts.Add(time.Duration(n) * at.t1)

	// allow bus idle time
	time.Sleep(at.lastActivity.Add(at.t35).Sub(time.Now()))

	res, err = at.readASCIIFrame()
	if err == ErrBadLRC || err == ErrProtocolError || err == ErrShortFrame {
		time.Sleep(time.Duration(maxASCIIFrameLength) * at.t1)
		discard(at.link)
	}

	if err != ErrRequestTimedOut {
		at.lastActivity = time.Now()
	}

	return
}

// Reads a request from the link.
func (at *asciiTransport) ReadRequest() (req *pdu, err error) {
	err = at.link.SetDeadline(time.Now().Add(at.timeout))
	if err != nil {
		return
	}

	req, err = at.readASCIIFrame()
	if err == nil {
		at.lastActivity = time.Now()
	}

	return
}

// Writes a response to the link.
func (at *asciiTransport) WriteResponse(res *pdu) (err error) {
	var n int

	err = at.link.SetDeadline(time.Now().Add(at.timeout))
	if err != nil {
		return
	}

	frame := at.assembleASCIIFrame(res)
	n, err = at.link.Write(frame)
	if err != nil {
		return
	}

	at.lastActivity = time.Now().Add(time.Duration(n) * at.t1)

	return
}

// Reads and decodes a frame from the link.
func (at *asciiTransport) readASCIIFrame() (res *pdu, err error) {
	var rxbuf []byte
	var tmp []byte
	var colon bool

	rxbuf = make([]byte, 0, maxASCIIFrameLength)
	tmp = make([]byte, 1)

	for {
		var cnt int

		cnt, err = at.link.Read(tmp)
		if err != nil {
			if os.IsTimeout(err) {
				err = ErrRequestTimedOut
			}
			return
		}

		if cnt == 0 {
			continue
		}

		b := tmp[0]

		if !colon {
			if b != ':' {
				// ignore noise until we find the start of a frame
				continue
			}
			colon = true
		}

		rxbuf = append(rxbuf, b)

		if len(rxbuf) > maxASCIIFrameLength {
			err = ErrProtocolError
			return
		}

		if b == '\n' {
			break
		}
	}

	if len(rxbuf) < 3 || rxbuf[len(rxbuf)-2] != '\r' {
		err = ErrProtocolError
		return
	}

	// strip ':' prefix and CRLF suffix
	hexPayload := rxbuf[1 : len(rxbuf)-2]

	// need at least address, function code and LRC i.e. 6 hex chars
	if len(hexPayload) < 6 {
		err = ErrShortFrame
		return
	}

	// hex payload must be even length
	if len(hexPayload)%2 != 0 {
		err = ErrProtocolError
		return
	}

	raw := make([]byte, len(hexPayload)/2)
	_, err = hex.Decode(raw, hexPayload)
	if err != nil {
		err = ErrProtocolError
		return
	}

	// need unit id, function code and LRC at minimum
	if len(raw) < 3 {
		err = ErrShortFrame
		return
	}

	data := raw[:len(raw)-1]
	lrc := raw[len(raw)-1]

	if !verifyLRC(data, lrc) {
		err = ErrBadLRC
		return
	}

	res = &pdu{
		unitId:       data[0],
		functionCode: data[1],
		payload:      data[2:],
	}

	return
}

// Turns a PDU object into an ASCII frame.
func (at *asciiTransport) assembleASCIIFrame(p *pdu) (frame []byte) {
	var buf []byte

	buf = append(buf, p.unitId, p.functionCode)
	buf = append(buf, p.payload...)

	lrc := computeLRC(buf)
	buf = append(buf, lrc)

	frame = make([]byte, 0, 1+len(buf)*2+2)
	frame = append(frame, ':')

	for _, b := range buf {
		frame = append(frame, toHexUpper(b)...)
	}

	frame = append(frame, '\r', '\n')

	return
}

func toHexUpper(b byte) (hexPair []byte) {
	const table = "0123456789ABCDEF"

	hexPair = []byte{table[b>>4], table[b&0x0f]}

	return
}
