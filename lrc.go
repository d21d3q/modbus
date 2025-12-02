package modbus

// computeLRC returns the Modbus ASCII LRC (Longitudinal Redundancy Check)
// for the provided bytes. The LRC is the two's complement of the sum of all
// bytes in the frame excluding the LRC itself.
func computeLRC(buf []byte) (lrc byte) {
	var sum byte

	for _, b := range buf {
		sum += b
	}

	lrc = byte(^sum + 1)

	return
}

// verifyLRC checks whether the provided LRC matches the computed value for buf.
func verifyLRC(buf []byte, lrc byte) (ok bool) {
	ok = computeLRC(buf) == lrc

	return
}
